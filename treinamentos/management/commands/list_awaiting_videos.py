from django.core.management.base import BaseCommand

from treinamentos.models import TrainingVideo
from treinamentos.services.pipeline import generation_params


class Command(BaseCommand):
    help = (
        "Lista os roteiros aprovados que aguardam a geração do vídeo na HeyGen, "
        "com o avatar, a voz e o roteiro de cada um."
    )

    def handle(self, *args, **options):
        videos = (
            TrainingVideo.objects.filter(status=TrainingVideo.Status.AWAITING_VIDEO)
            .select_related("department")
            .order_by("created_at")
        )
        if not videos:
            self.stdout.write("Nenhum roteiro aguardando vídeo.")
            return

        for video in videos:
            params = generation_params(video)
            self.stdout.write(self.style.SUCCESS(f"[{video.id}] {video.department.name} — {video.title}"))
            self.stdout.write(f"  avatar: {params['avatar_id'] or '(não definido)'}")
            self.stdout.write(f"  voz:    {params['voice_id'] or '(não definida)'}")
            self.stdout.write(f"  roteiro ({len(video.script_text)} caracteres):")
            for line in video.script_text.splitlines() or [""]:
                self.stdout.write(f"    {line}")
            self.stdout.write("")
        self.stdout.write(
            "Depois de gerar, registre com:  manage.py register_video <id> --heygen-id <id da HeyGen> "
            "[--url <link do MP4> --duration <segundos>]"
        )
