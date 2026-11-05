"""
Pipeline: documento -> roteiro (o próprio texto do documento) -> [revisão do gestor] -> aguardando vídeo.

O vídeo é gerado fora do portal (Claude + MCP da HeyGen) e volta pelo conector MCP, pela tela
"Anexar vídeo" ou pela pasta Vídeos do Drive. A leitura do documento roda em thread de background.
"""
import logging
import os
import threading
from pathlib import Path
from typing import Optional

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

from treinamentos.models import TrainingVideo
from treinamentos.services.drive_service import GoogleDriveService
from treinamentos.services.document_parser import DocumentParser, clean_script

logger = logging.getLogger(__name__)
Status = TrainingVideo.Status

# Limite de caracteres de um roteiro (limite da HeyGen para um único bloco de fala).
MAX_SCRIPT_CHARS = 5000

_running: set[int] = set()
_running_lock = threading.Lock()


def start_pipeline_async(video_id: int) -> bool:
    """Lê o documento e prepara o roteiro em uma thread. Retorna False se o vídeo já está sendo processado."""
    with _running_lock:
        if video_id in _running:
            return False
        _running.add(video_id)

    def _worker():
        close_old_connections()
        try:
            process_training_video(video_id)
        finally:
            with _running_lock:
                _running.discard(video_id)
            close_old_connections()

    threading.Thread(target=_worker, name=f"pipeline-{video_id}", daemon=True).start()
    return True


def resolve_source_file(video: TrainingVideo) -> Optional[Path]:
    if not video.source_path:
        return None
    p = Path(video.source_path)
    if not p.is_absolute():
        p = settings.BASE_DIR / p
    return p if p.is_file() else None


def _load(video_id: int) -> Optional[TrainingVideo]:
    try:
        return TrainingVideo.objects.select_related('department').get(id=video_id)
    except TrainingVideo.DoesNotExist:
        logger.error("Vídeo %s não encontrado.", video_id)
        return None


def validate_script(script: str) -> None:
    if not script.strip():
        raise ValueError("O roteiro está vazio.")
    if len(script) > MAX_SCRIPT_CHARS:
        raise ValueError(
            f"Roteiro com {len(script)} caracteres; o limite da HeyGen é {MAX_SCRIPT_CHARS}. "
            "Reduza o texto ou divida o documento em partes menores."
        )


def process_training_video(video_id: int) -> None:
    """Etapa 1: lê o documento e prepara o roteiro. Com revisão ativa, para aqui até o gestor aprovar."""
    video = _load(video_id)
    if not video:
        return
    try:
        video.set_status(Status.PARSING, "Lendo o documento e preparando o roteiro...")
        file_path = resolve_source_file(video)
        if not file_path:
            raise FileNotFoundError(f"Arquivo não localizado no servidor: {video.file_name}")
        raw_text, _ = DocumentParser.extract_text(file_path)
        video.script_text = clean_script(raw_text)
        video.save(update_fields=['script_text'])

        if settings.REQUIRE_SCRIPT_REVIEW:
            video.set_status(
                Status.AWAITING_REVIEW,
                "Roteiro pronto. Revise e aprove para gerar o vídeo.",
            )
            return
        mark_awaiting_video(video)
    except Exception as exc:  # noqa: BLE001 - qualquer falha marca o job como FAILED
        logger.exception("Erro no pipeline do vídeo %s", video_id)
        video.set_status(Status.FAILED, f"Erro no processamento: {exc}")


def generation_params(video: TrainingVideo) -> dict:
    """Avatar e voz a usar neste vídeo: os do setor e, se vazios, os padrões do .env."""
    dept = video.department
    return {
        "avatar_id": dept.avatar_id or os.getenv("DEFAULT_AVATAR_ID", ""),
        "voice_id": dept.voice_id or os.getenv("DEFAULT_VOICE_ID", ""),
    }


def mark_awaiting_video(video: TrainingVideo) -> None:
    """Roteiro aprovado, mas o vídeo é gerado fora do portal (MCP/site da HeyGen): fica esperando o registro."""
    validate_script(video.script_text)
    video.set_status(Status.AWAITING_VIDEO, "Roteiro aprovado. Aguardando a geração do vídeo.")


def save_generated_video(
    video: TrainingVideo, *, video_url: str, heygen_video_id: str = "", duration: float = 0.0,
    thumbnail_url: str = "", publish: bool = False,
) -> str:
    """
    Salva no Drive (<Setor>/Vídeos) um vídeo gerado na HeyGen fora do portal e devolve o ID do arquivo.
    publish=False: o item continua aguardando e só entra no catálogo na próxima sincronização do Drive.
    publish=True: o item já é concluído e publicado.
    """
    if video.status not in (Status.AWAITING_VIDEO, Status.GENERATING_HEYGEN):
        raise ValueError(
            f"O vídeo está em '{video.get_status_display()}'. Só aceita itens 'Aguardando Vídeo' ou 'HeyGen Renderizando'."
        )
    if video.drive_video_id:
        raise ValueError("Este item já tem um vídeo salvo no Drive.")

    video.video_url = video_url
    video.thumbnail_url = thumbnail_url or ""
    video.duration_seconds = duration or 0.0
    if heygen_video_id:
        video.heygen_video_id = heygen_video_id

    file_id = GoogleDriveService.upload_video(video)
    if not file_id:
        raise RuntimeError(
            f"Não foi possível salvar no Drive: o setor {video.department.name} não tem pasta cadastrada "
            "ou a Service Account não está configurada."
        )

    common = {
        "video_url": video.video_url, "thumbnail_url": video.thumbnail_url,
        "duration_seconds": video.duration_seconds, "heygen_video_id": video.heygen_video_id,
    }
    if publish:
        video.set_status(
            Status.COMPLETED, "Vídeo concluído e disponível para o setor",
            drive_video_id=file_id, completed_at=timezone.now(), **common,
        )
    else:
        video.set_status(
            video.status,
            "Vídeo salvo na pasta Vídeos do Drive. Clique em 'Sincronizar Drive' para publicar no catálogo.",
            **common,
        )
    return file_id


def attach_uploaded_video(video: TrainingVideo, path: Path, duration: float = 0.0) -> None:
    """Registra um MP4 anexado no portal (gerado fora): guarda no Drive e publica no catálogo."""
    file_id = GoogleDriveService.upload_video_file(video, path)
    video.set_status(
        Status.COMPLETED,
        "Vídeo anexado e salvo na pasta Vídeos do setor no Drive",
        drive_video_id=file_id,
        duration_seconds=duration or 0.0,
        completed_at=timezone.now(),
    )
