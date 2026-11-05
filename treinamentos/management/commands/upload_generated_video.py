from django.core.management.base import BaseCommand, CommandError

from treinamentos.models import TrainingVideo
from treinamentos.services.drive_service import GoogleDriveService

Status = TrainingVideo.Status


class Command(BaseCommand):
    help = (
        "Salva na pasta Vídeos do setor, no Drive, um vídeo já gerado na HeyGen (por exemplo, pelo MCP).\n"
        "O vídeo só entra no catálogo quando alguém clica em 'Sincronizar Drive' (ou roda sync_drive)."
    )

    def add_arguments(self, parser):
        parser.add_argument("video_id", type=int, help="ID do item na fila do portal")
        parser.add_argument("--url", required=True, help="Link do MP4 gerado pela HeyGen")
        parser.add_argument("--heygen-id", default="", help="ID do vídeo na HeyGen")
        parser.add_argument("--duration", type=float, default=0.0, help="Duração em segundos")
        parser.add_argument("--thumbnail", default="", help="Link da miniatura")

    def handle(self, *args, **options):
        try:
            video = TrainingVideo.objects.select_related("department").get(id=options["video_id"])
        except TrainingVideo.DoesNotExist:
            raise CommandError(f"Vídeo {options['video_id']} não encontrado.")

        if video.status not in (Status.AWAITING_VIDEO, Status.GENERATING_HEYGEN):
            raise CommandError(
                f"O vídeo está em '{video.get_status_display()}'. Só é possível enviar itens "
                "'Aguardando Vídeo' ou 'HeyGen Renderizando'."
            )
        if video.drive_video_id:
            raise CommandError("Este item já tem um vídeo salvo no Drive.")

        video.video_url = options["url"]
        video.thumbnail_url = options["thumbnail"]
        video.duration_seconds = options["duration"]
        if options["heygen_id"]:
            video.heygen_video_id = options["heygen_id"]

        try:
            file_id = GoogleDriveService.upload_video(video)
        except Exception as exc:  # noqa: BLE001
            raise CommandError(f"Falha ao enviar o vídeo ao Drive: {exc}")
        if not file_id:
            raise CommandError(
                f"Não foi possível salvar no Drive: o setor {video.department.name} não tem pasta cadastrada "
                "ou a Service Account não está configurada."
            )

        # O item continua aguardando: quem publica no catálogo é a sincronização, que liga o arquivo ao item.
        video.set_status(
            video.status,
            "Vídeo salvo na pasta Vídeos do Drive. Clique em 'Sincronizar Drive' para publicar no catálogo.",
            video_url=video.video_url,
            thumbnail_url=video.thumbnail_url,
            duration_seconds=video.duration_seconds,
            heygen_video_id=video.heygen_video_id,
        )
        self.stdout.write(self.style.SUCCESS(f"[{video.id}] vídeo salvo no Drive (arquivo {file_id})."))
        self.stdout.write("Agora clique em 'Sincronizar Drive' no portal (ou rode manage.py sync_drive) para publicar.")
