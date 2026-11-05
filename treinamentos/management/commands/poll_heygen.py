from django.core.management.base import BaseCommand

from treinamentos.models import TrainingVideo
from treinamentos.services.pipeline import archive_video_to_drive, refresh_heygen_status


class Command(BaseCommand):
    help = "Consulta a HeyGen e atualiza os vídeos que ainda estão em renderização."

    def handle(self, *args, **options):
        pending = TrainingVideo.objects.filter(
            status=TrainingVideo.Status.GENERATING_HEYGEN
        ).exclude(heygen_video_id='')

        # Vídeos prontos que ainda não foram copiados para a pasta Vídeos do Drive (ex.: falha anterior).
        to_archive = TrainingVideo.objects.filter(status=TrainingVideo.Status.COMPLETED, drive_video_id='')             .exclude(heygen_video_id='')             .exclude(department__drive_folder_id='').exclude(video_url='')
        for video in to_archive:
            archive_video_to_drive(video)
            self.stdout.write(f"[{video.id}] {video.title}: Drive -> {'salvo' if video.drive_video_id else 'pendente'}")

        if not pending.exists():
            self.stdout.write("Nenhum vídeo aguardando a HeyGen.")
            return

        for video in pending:
            try:
                status = refresh_heygen_status(video)
                self.stdout.write(f"[{video.id}] {video.title}: HeyGen={status or '?'} -> {video.get_status_display()}")
            except Exception as exc:  # noqa: BLE001
                self.stderr.write(self.style.ERROR(f"[{video.id}] {video.title}: {exc}"))
