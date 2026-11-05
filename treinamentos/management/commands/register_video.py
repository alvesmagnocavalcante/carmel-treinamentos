from django.core.management.base import BaseCommand, CommandError

from treinamentos.models import TrainingVideo
from treinamentos.services.pipeline import complete_video

Status = TrainingVideo.Status


class Command(BaseCommand):
    help = (
        "Registra no portal um vídeo gerado na HeyGen fora do sistema (por exemplo, pelo MCP).\n"
        "  Só com --heygen-id: marca o item como 'HeyGen Renderizando'.\n"
        "  Com --heygen-id e --url: conclui, publica no catálogo e salva uma cópia no Drive."
    )

    def add_arguments(self, parser):
        parser.add_argument("video_id", type=int, help="ID do item na fila do portal")
        parser.add_argument("--heygen-id", required=True, help="ID do vídeo na HeyGen")
        parser.add_argument("--url", default="", help="Link do MP4 (quando o vídeo já está pronto)")
        parser.add_argument("--duration", type=float, default=0.0, help="Duração em segundos")
        parser.add_argument("--thumbnail", default="", help="Link da miniatura")

    def handle(self, *args, **options):
        try:
            video = TrainingVideo.objects.select_related("department").get(id=options["video_id"])
        except TrainingVideo.DoesNotExist:
            raise CommandError(f"Vídeo {options['video_id']} não encontrado.")

        if video.status == Status.COMPLETED:
            raise CommandError("Este vídeo já está concluído.")
        if video.status not in (Status.AWAITING_VIDEO, Status.GENERATING_HEYGEN):
            raise CommandError(
                f"O vídeo está em '{video.get_status_display()}'. Só é possível registrar itens "
                "'Aguardando Vídeo' ou 'HeyGen Renderizando'."
            )

        if not options["url"]:
            video.set_status(
                Status.GENERATING_HEYGEN,
                "Renderizando vídeo com Avatar Digital na HeyGen...",
                heygen_video_id=options["heygen_id"],
            )
            self.stdout.write(self.style.SUCCESS(f"[{video.id}] marcado como 'HeyGen Renderizando'."))
            return

        complete_video(
            video,
            video_url=options["url"],
            heygen_video_id=options["heygen_id"],
            thumbnail_url=options["thumbnail"],
            duration=options["duration"],
        )
        video.refresh_from_db()
        self.stdout.write(self.style.SUCCESS(f"[{video.id}] {video.get_status_display()}: {video.status_message}"))
