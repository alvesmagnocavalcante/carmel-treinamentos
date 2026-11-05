import time

from django.conf import settings
from django.core.management.base import BaseCommand

from treinamentos.services.drive_service import GoogleDriveService
from treinamentos.services.pipeline import process_training_video


class Command(BaseCommand):
    help = "Varre as pastas de cada setor (Google Drive) e processa novos documentos."

    def add_arguments(self, parser):
        parser.add_argument(
            '--watch', action='store_true',
            help="Fica em execução contínua, varrendo a cada DRIVE_SYNC_INTERVAL_MINUTES minutos.",
        )

    def handle(self, *args, **options):
        if not options['watch']:
            self.run_once()
            return

        interval = max(1, settings.DRIVE_SYNC_INTERVAL_MINUTES)
        self.stdout.write(f"Modo contínuo: varrendo a cada {interval} minuto(s). Ctrl+C para parar.")
        try:
            while True:
                self.run_once()
                time.sleep(interval * 60)
        except KeyboardInterrupt:
            self.stdout.write("Encerrado.")

    def run_once(self):
        self.stdout.write("Varrendo as pastas dos setores...")
        result = GoogleDriveService.scan_all_departments()
        if not result['drive_connected']:
            self.stdout.write(self.style.WARNING("Google Drive não configurado: nada foi sincronizado."))
        for err in result['errors']:
            self.stderr.write(self.style.ERROR(err))

        self.stdout.write(self.style.SUCCESS(f"{result['found']} novo(s) roteiro(s) encontrado(s)."))
        self.stdout.write(self.style.SUCCESS(f"{result['published']} vídeo(s) publicado(s) a partir da pasta Vídeos."))
        for video in result['published_videos']:
            self.stdout.write(f"  publicado: [{video.department.name}] {video.title}")
        for video in result['new_videos']:
            self.stdout.write(f"Processando: [{video.department.name}] {video.title}")
            process_training_video(video.id)
            video.refresh_from_db()
            self.stdout.write(f"  -> {video.get_status_display()}: {video.status_message}")
