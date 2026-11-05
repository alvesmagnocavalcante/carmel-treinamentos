"""
Pipeline: documento -> roteiro (o próprio texto do documento) -> [revisão do gestor] -> vídeo HeyGen -> catálogo.

Roda em threads de background (servidor de desenvolvimento / uso interno).
Se o servidor reiniciar no meio de uma renderização, rode
`python manage.py poll_heygen` para retomar a consulta dos vídeos pendentes.
"""
import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

from treinamentos.models import TrainingVideo
from treinamentos.services.drive_service import GoogleDriveService
from treinamentos.services.document_parser import DocumentParser, clean_script
from treinamentos.services.heygen_service import MAX_SCRIPT_CHARS, HeyGenService

logger = logging.getLogger(__name__)
Status = TrainingVideo.Status

_running: set[int] = set()
_running_lock = threading.Lock()


def start_pipeline_async(video_id: int, target=None) -> bool:
    """
    Dispara uma etapa do pipeline em uma thread (por padrão, a leitura do documento).
    Retorna False se o vídeo já está sendo processado.
    """
    target = target or process_training_video
    with _running_lock:
        if video_id in _running:
            return False
        _running.add(video_id)

    def _worker():
        close_old_connections()
        try:
            target(video_id)
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
                f"Roteiro pronto ({len(video.script_text)} caracteres). Revise e aprove para gerar o vídeo.",
            )
            return
        _generate_or_wait(video)
    except Exception as exc:  # noqa: BLE001 - qualquer falha marca o job como FAILED
        logger.exception("Erro no pipeline do vídeo %s", video_id)
        video.set_status(Status.FAILED, f"Erro no processamento: {exc}")


def approve_and_generate(video_id: int) -> None:
    """Etapa 2 (após a revisão): envia o roteiro aprovado à HeyGen e acompanha a renderização."""
    video = _load(video_id)
    if not video:
        return
    try:
        _send_to_heygen(video)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Erro ao gerar o vídeo %s", video_id)
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
    params = generation_params(video)
    video.set_status(
        Status.AWAITING_VIDEO,
        f"Roteiro aprovado ({len(video.script_text)} caracteres). Aguardando a geração do vídeo na HeyGen "
        f"(avatar {params['avatar_id'] or '?'}, voz {params['voice_id'] or '?'}).",
    )


def _generate_or_wait(video: TrainingVideo) -> None:
    if settings.HEYGEN_GENERATION_MODE == "api":
        _send_to_heygen(video)
    else:
        mark_awaiting_video(video)


def complete_video(
    video: TrainingVideo, *, video_url: str, heygen_video_id: str = "", thumbnail_url: str = "", duration: float = 0.0
) -> None:
    """Registra um vídeo já gerado na HeyGen: publica no catálogo e guarda a cópia no Drive."""
    fields = {
        "video_url": video_url,
        "thumbnail_url": thumbnail_url or "",
        "duration_seconds": duration or 0.0,
        "completed_at": timezone.now(),
    }
    if heygen_video_id:
        fields["heygen_video_id"] = heygen_video_id
    video.set_status(Status.COMPLETED, "Vídeo concluído e disponível para o setor", **fields)
    archive_video_to_drive(video)


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


def _send_to_heygen(video: TrainingVideo) -> None:
    validate_script(video.script_text)
    video.set_status(Status.GENERATING_HEYGEN, "Enviando roteiro para o Avatar Digital da HeyGen...")
    result = HeyGenService.generate_video(
        script_text=video.script_text,
        avatar_id=video.department.avatar_id,
        voice_id=video.department.voice_id,
        title=f"Treinamento Carmel: {video.title}",
    )
    video.set_status(
        Status.GENERATING_HEYGEN,
        "Renderizando vídeo com Avatar Digital no HeyGen...",
        heygen_video_id=result["video_id"],
        video_url="",
        thumbnail_url="",
        completed_at=None,
    )
    if result.get("mock"):
        time.sleep(2)  # feedback visual na fila
    wait_for_heygen(video)


def refresh_heygen_status(video: TrainingVideo) -> str:
    """Consulta a HeyGen uma vez e atualiza o vídeo. Retorna o status da HeyGen."""
    info = HeyGenService.check_video_status(video.heygen_video_id)
    status = info.get("status", "")

    if status == "completed" and info.get("video_url"):
        complete_video(
            video,
            video_url=info["video_url"],
            thumbnail_url=info.get("thumbnail_url") or "",
            duration=info.get("duration") or 0.0,
        )
        logger.info("Vídeo '%s' concluído.", video.title)
    elif status == "failed":
        video.set_status(Status.FAILED, f"HeyGen falhou ao renderizar: {info.get('error') or 'erro desconhecido'}")
    return status


def archive_video_to_drive(video: TrainingVideo) -> None:
    """Salva uma cópia do vídeo pronto em <setor>/Vídeos no Drive. Falha aqui não derruba o vídeo."""
    if video.drive_video_id or not video.video_url or HeyGenService.is_mock_id(video.heygen_video_id):
        return
    try:
        file_id = GoogleDriveService.upload_video(video)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha ao salvar o vídeo %s no Drive", video.id)
        video.set_status(
            Status.COMPLETED,
            f"Vídeo concluído, mas não foi salvo no Drive ({exc}). Será tentado de novo no próximo 'poll_heygen'.",
        )
        return
    if file_id:
        video.set_status(Status.COMPLETED, "Vídeo concluído e salvo na pasta Vídeos do setor no Drive", drive_video_id=file_id)


def wait_for_heygen(video: TrainingVideo) -> None:
    """Consulta a HeyGen periodicamente até concluir, falhar ou estourar o tempo limite."""
    deadline = time.monotonic() + settings.HEYGEN_POLL_TIMEOUT_MINUTES * 60
    while True:
        status = refresh_heygen_status(video)
        if status in ("completed", "failed") and video.status != Status.GENERATING_HEYGEN:
            return
        if time.monotonic() >= deadline:
            video.set_status(
                Status.GENERATING_HEYGEN,
                "Renderização ainda em andamento na HeyGen. Rode 'manage.py poll_heygen' para atualizar.",
            )
            return
        time.sleep(settings.HEYGEN_POLL_INTERVAL_SECONDS)
