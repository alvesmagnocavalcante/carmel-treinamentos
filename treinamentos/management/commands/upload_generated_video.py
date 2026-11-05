from django.core.management.base import BaseCommand, CommandError

from treinamentos.models import TrainingVideo
from treinamentos.services.pipeline import save_generated_video


class Command(BaseCommand):
    help = (
        "Salva na pasta Vídeos do setor, no Drive, um vídeo já gerado na HeyGen (por exemplo, pelo MCP).\n"
        "O vídeo só entra no catálogo quando alguém clica em 'Sincronizar Drive' (ou roda sync_drive); "
        "use --publish para publicar na hora."
    )

    def add_arguments(self, parser):
        parser.add_argument("video_id", type=int, help="ID do item na fila do portal")
        parser.add_argument("--url", required=True, help="Link do MP4 gerado pela HeyGen")
        parser.add_argument("--heygen-id", default="", help="ID do vídeo na HeyGen")
        parser.add_argument("--duration", type=float, default=0.0, help="Duração em segundos")
        parser.add_argument("--thumbnail", default="", help="Link da miniatura")
        parser.add_argument("--publish", action="store_true", help="Conclui e publica o item na hora")

    def handle(self, *args, **options):
        try:
            video = TrainingVideo.objects.select_related("department").get(id=options["video_id"])
        except TrainingVideo.DoesNotExist:
            raise CommandError(f"Vídeo {options['video_id']} não encontrado.")

        try:
            file_id = save_generated_video(
                video,
                video_url=options["url"],
                heygen_video_id=options["heygen_id"],
                duration=options["duration"],
                thumbnail_url=options["thumbnail"],
                publish=options["publish"],
            )
        except (ValueError, RuntimeError) as exc:
            raise CommandError(str(exc))
        except Exception as exc:  # noqa: BLE001
            raise CommandError(f"Falha ao enviar o vídeo ao Drive: {exc}")

        self.stdout.write(self.style.SUCCESS(f"[{video.id}] vídeo salvo no Drive (arquivo {file_id})."))
        if options["publish"]:
            self.stdout.write("Item concluído e publicado no catálogo.")
        else:
            self.stdout.write("Agora clique em 'Sincronizar Drive' no portal (ou rode manage.py sync_drive) para publicar.")
