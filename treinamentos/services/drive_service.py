import logging
import shutil
import tempfile
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from django.conf import settings
from django.utils import timezone

from treinamentos.models import Department, SystemSetting, TrainingVideo
from treinamentos.services.storage import is_allowed_extension, new_source_path, safe_filename, title_from_filename

logger = logging.getLogger(__name__)

# Leitura dos roteiros + escrita dos vídeos gerados (e criação das subpastas, se faltarem).
SCOPES = ['https://www.googleapis.com/auth/drive']

# Estrutura esperada dentro da pasta de cada setor.
FOLDER_MIME = 'application/vnd.google-apps.folder'
SCRIPTS_FOLDER = 'Roteiros'
VIDEOS_FOLDER = 'Vídeos'

# Google Docs nativos não podem ser baixados diretamente: exportamos como .docx.
GOOGLE_DOC_MIME = 'application/vnd.google-apps.document'
DOCX_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
SUPPORTED_MIMES = {
    'application/pdf': '.pdf',
    DOCX_MIME: '.docx',
    'text/plain': '.txt',
    'text/markdown': '.md',
    GOOGLE_DOC_MIME: '.docx',
}


def _norm(name: str) -> str:
    """'Vídeos' == 'videos' == 'VÍDEOS' (tolera acento e caixa nos nomes das pastas)."""
    return unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode().strip().casefold()


class GoogleDriveService:
    @staticmethod
    def get_service_account_path() -> Optional[Path]:
        raw = SystemSetting.get_val("google_service_account_file", settings.GOOGLE_SERVICE_ACCOUNT_FILE)
        p = Path(raw)
        if not p.is_absolute():
            p = settings.BASE_DIR / p
        return p if p.is_file() else None

    _credentials = {}

    @classmethod
    def _access_token(cls) -> Optional[str]:
        """Token OAuth da Service Account (renovado automaticamente quando expira)."""
        sa_path = cls.get_service_account_path()
        if not sa_path:
            return None
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account

        creds = cls._credentials.get(sa_path)
        if creds is None:
            creds = service_account.Credentials.from_service_account_file(str(sa_path), scopes=SCOPES)
            cls._credentials[sa_path] = creds
        if not creds.valid:
            creds.refresh(Request())
        return creds.token

    @classmethod
    def open_file_stream(cls, file_id: str, range_header: str = ""):
        """
        Abre o conteúdo de um arquivo do Drive em streaming (aceita cabeçalho Range, para o player
        poder avançar/voltar). Retorna (client, response) do httpx — quem chama deve fechar ambos.
        """
        token = cls._access_token()
        if not token:
            raise RuntimeError("Google Drive não configurado.")
        headers = {"Authorization": f"Bearer {token}"}
        if range_header:
            headers["Range"] = range_header
        client = httpx.Client(timeout=httpx.Timeout(30.0, read=120.0))
        try:
            request = client.build_request(
                "GET", f"https://www.googleapis.com/drive/v3/files/{file_id}",
                params={"alt": "media", "supportsAllDrives": "true"}, headers=headers,
            )
            return client, client.send(request, stream=True)
        except Exception:
            client.close()
            raise

    @classmethod
    def get_drive_client(cls):
        sa_path = cls.get_service_account_path()
        if not sa_path:
            return None
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        creds = service_account.Credentials.from_service_account_file(str(sa_path), scopes=SCOPES)
        return build('drive', 'v3', credentials=creds, cache_discovery=False)

    @classmethod
    def scan_all_departments(cls, departments=None) -> Dict[str, Any]:
        """
        Varre as pastas locais de simulação (data/mock_drive/<código_do_setor>/) e,
        se houver Service Account configurada, as pastas reais do Google Drive.
        """
        departments = list(departments if departments is not None else Department.objects.all())
        new_videos: List[TrainingVideo] = []
        published: List[TrainingVideo] = []
        errors: List[str] = []

        new_videos += cls._scan_mock_folders(departments)

        client = cls.get_drive_client()
        if client:
            for dept in departments:
                if not dept.drive_folder_id:
                    continue
                try:
                    new_videos += cls._scan_drive_folder(client, dept)
                    published += cls._scan_videos_folder(client, dept)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Erro ao varrer a pasta do setor %s", dept.name)
                    errors.append(f"{dept.name}: {exc}")

        return {
            "found": len(new_videos), "new_videos": new_videos,
            "published": len(published), "published_videos": published,
            "errors": errors, "drive_connected": bool(client),
        }

    @staticmethod
    def _scan_mock_folders(departments) -> List[TrainingVideo]:
        mock_root = Path(settings.MOCK_DRIVE_DIR)
        created = []
        for dept in departments:
            sector = mock_root / dept.code
            folder = sector / SCRIPTS_FOLDER
            folder.mkdir(parents=True, exist_ok=True)
            (sector / VIDEOS_FOLDER).mkdir(exist_ok=True)
            for file_path in sorted(folder.iterdir()):
                if not file_path.is_file() or not is_allowed_extension(file_path.name):
                    continue
                # Formato do ID mantido igual ao das versões anteriores (evita reprocessar arquivos).
                drive_id = f"local_{file_path.name}_{int(file_path.stat().st_mtime)}"
                if TrainingVideo.objects.filter(department=dept, drive_file_id=drive_id).exists():
                    continue
                dest = new_source_path(f"local_{dept.code}", file_path.name)
                shutil.copy2(file_path, dest)
                created.append(TrainingVideo.objects.create(
                    department=dept,
                    title=title_from_filename(file_path.name),
                    file_name=file_path.name,
                    source_path=str(dest),
                    drive_file_id=drive_id,
                    status=TrainingVideo.Status.PENDING,
                    status_message="Arquivo encontrado na pasta local do setor",
                ))
        return created

    @staticmethod
    def _list_folder(client, folder_id: str) -> List[dict]:
        files, page_token = [], None
        query = f"'{folder_id}' in parents and trashed = false and mimeType != 'application/vnd.google-apps.folder'"
        while True:
            resp = client.files().list(
                q=query,
                fields="nextPageToken, files(id, name, mimeType, modifiedTime, appProperties)",
                pageSize=100,
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute()
            files.extend(resp.get('files', []))
            page_token = resp.get('nextPageToken')
            if not page_token:
                return files

    @staticmethod
    def _get_or_create_subfolder(client, parent_id: str, name: str) -> str:
        """Acha a subfolder `name` (sem diferenciar acento/caixa) dentro de `parent_id`; cria se não existir."""
        resp = client.files().list(
            q=f"'{parent_id}' in parents and trashed = false and mimeType = '{FOLDER_MIME}'",
            fields="files(id, name)", pageSize=200,
            supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute()
        for f in resp.get('files', []):
            if _norm(f['name']) == _norm(name):
                return f['id']
        created = client.files().create(
            body={'name': name, 'mimeType': FOLDER_MIME, 'parents': [parent_id]},
            fields='id', supportsAllDrives=True,
        ).execute()
        logger.info("Subpasta '%s' criada no Drive.", name)
        return created['id']

    @classmethod
    def _put_video_in_drive(cls, client, dept: Department, name: str, path: Path, properties: Optional[dict] = None) -> str:
        """Grava o arquivo `path` na subpasta Vídeos do setor e devolve o ID no Drive."""
        from googleapiclient.http import MediaIoBaseUpload

        folder_id = cls._get_or_create_subfolder(client, dept.drive_folder_id, VIDEOS_FOLDER)
        # Arquivo aberto só dentro do "with": no Windows, um handle esquecido impede apagar a pasta temporária.
        with open(path, "rb") as fh:
            media = MediaIoBaseUpload(fh, mimetype="video/mp4", resumable=True)
            uploaded = client.files().create(
                body={'name': name, 'parents': [folder_id], 'appProperties': properties or {}},
                media_body=media, fields='id', supportsAllDrives=True,
            ).execute()
        return uploaded['id']

    @staticmethod
    def _video_properties(video: TrainingVideo) -> dict:
        """Dados gravados no arquivo do Drive: a sincronização usa isso para ligar o MP4 ao item certo."""
        props = {"carmel_video_id": str(video.id)}
        if video.heygen_video_id:
            props["heygen_video_id"] = video.heygen_video_id
        if video.duration_seconds:
            props["duration"] = str(video.duration_seconds)
        return props

    @staticmethod
    def _video_file_name(video: TrainingVideo) -> str:
        return f"{safe_filename(video.title)}.mp4" if video.title else f"video_{video.id}.mp4"

    @classmethod
    def upload_video(cls, video: TrainingVideo) -> Optional[str]:
        """
        Baixa o MP4 gerado pela HeyGen (video_url) e o copia para <pasta do setor>/Vídeos no Drive.
        Retorna o ID do arquivo no Drive, ou None se não há Drive/pasta configurados.
        """
        dept = video.department
        client = cls.get_drive_client()
        if not client or not dept.drive_folder_id or not video.video_url:
            return None

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "video.mp4"
            with httpx.stream("GET", video.video_url, follow_redirects=True, timeout=120.0) as resp:
                resp.raise_for_status()
                limit = settings.MAX_VIDEO_MB * 1024 * 1024
                size = 0
                with open(path, "wb") as fh:
                    for chunk in resp.iter_bytes(1024 * 1024):
                        size += len(chunk)
                        if size > limit:
                            raise ValueError(f"O vídeo passa do limite de {settings.MAX_VIDEO_MB} MB.")
                        fh.write(chunk)
            return cls._put_video_in_drive(
                client, dept, cls._video_file_name(video), path, cls._video_properties(video)
            )

    @classmethod
    def upload_video_file(cls, video: TrainingVideo, path: Path) -> str:
        """Copia um MP4 local (anexado no portal) para <pasta do setor>/Vídeos. Falha se o Drive não estiver pronto."""
        dept = video.department
        client = cls.get_drive_client()
        if not client:
            raise RuntimeError("Google Drive não configurado (falta a Service Account).")
        if not dept.drive_folder_id:
            raise RuntimeError(f"O setor {dept.name} não tem pasta do Drive cadastrada.")
        return cls._put_video_in_drive(
            client, dept, cls._video_file_name(video), Path(path), cls._video_properties(video)
        )

    @staticmethod
    def _match_waiting_video(dept: Department, name: str, props: dict) -> Optional[TrainingVideo]:
        """Acha o item do setor que está esperando este vídeo: pelo ID gravado no arquivo ou pelo título."""
        waiting = TrainingVideo.objects.filter(
            department=dept,
            status__in=[TrainingVideo.Status.AWAITING_VIDEO, TrainingVideo.Status.GENERATING_HEYGEN],
            drive_video_id="",
        ).order_by("created_at")
        item_id = str(props.get("carmel_video_id") or "")
        if item_id.isdigit():
            found = waiting.filter(id=int(item_id)).first()
            if found:
                return found
        wanted = _norm(title_from_filename(name))
        return next((v for v in waiting if _norm(v.title) == wanted), None)

    @classmethod
    def _scan_videos_folder(cls, client, dept: Department) -> List[TrainingVideo]:
        """
        Publica no catálogo os MP4 novos da subpasta Vídeos do setor. Se o arquivo corresponde a um item
        que aguarda o vídeo, esse item é concluído; senão, o vídeo entra como um item novo.
        """
        videos_folder = cls._get_or_create_subfolder(client, dept.drive_folder_id, VIDEOS_FOLDER)
        published = []
        for f in cls._list_folder(client, videos_folder):
            file_id, name = f["id"], f["name"]
            if not (f.get("mimeType") == "video/mp4" or name.lower().endswith(".mp4")):
                continue
            if TrainingVideo.objects.filter(drive_video_id=file_id).exists():
                continue

            props = f.get("appProperties") or {}
            try:
                duration = float(props.get("duration") or 0)
            except ValueError:
                duration = 0.0
            heygen_id = props.get("heygen_video_id") or ""

            video = cls._match_waiting_video(dept, name, props)
            if video:
                video.set_status(
                    TrainingVideo.Status.COMPLETED,
                    "Vídeo carregado da pasta Vídeos do Drive e disponível para o setor",
                    drive_video_id=file_id,
                    duration_seconds=duration or video.duration_seconds,
                    heygen_video_id=heygen_id or video.heygen_video_id,
                    completed_at=timezone.now(),
                )
            else:
                video = TrainingVideo.objects.create(
                    department=dept,
                    title=title_from_filename(name),
                    file_name=name,
                    status=TrainingVideo.Status.COMPLETED,
                    status_message="Vídeo importado da pasta Vídeos do Drive",
                    drive_video_id=file_id,
                    duration_seconds=duration,
                    heygen_video_id=heygen_id,
                    completed_at=timezone.now(),
                )
            published.append(video)
        return published

    @classmethod
    def _scan_drive_folder(cls, client, dept: Department) -> List[TrainingVideo]:
        from googleapiclient.http import MediaIoBaseDownload

        scripts_folder = cls._get_or_create_subfolder(client, dept.drive_folder_id, SCRIPTS_FOLDER)
        cls._get_or_create_subfolder(client, dept.drive_folder_id, VIDEOS_FOLDER)  # garante a estrutura

        created = []
        for f in cls._list_folder(client, scripts_folder):
            file_id, name, mime = f["id"], f["name"], f.get("mimeType", "")
            ext = SUPPORTED_MIMES.get(mime) or (Path(name).suffix.lower() if is_allowed_extension(name) else None)
            if not ext:
                logger.info("Ignorando arquivo não suportado no Drive: %s (%s)", name, mime)
                continue
            if TrainingVideo.objects.filter(drive_file_id=file_id).exists():
                continue

            local_name = name if Path(name).suffix.lower() == ext else f"{name}{ext}"
            dest = new_source_path(f"drive_{dept.code}", local_name)
            if mime == GOOGLE_DOC_MIME:
                request = client.files().export_media(fileId=file_id, mimeType=DOCX_MIME)
            else:
                request = client.files().get_media(fileId=file_id, supportsAllDrives=True)

            with open(dest, 'wb') as fh:
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()

            created.append(TrainingVideo.objects.create(
                department=dept,
                title=title_from_filename(name),
                file_name=local_name,
                source_path=str(dest),
                drive_file_id=file_id,
                status=TrainingVideo.Status.PENDING,
                status_message="Baixado do Google Drive",
            ))
        return created
