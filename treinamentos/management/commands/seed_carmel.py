from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from treinamentos.models import Department, SystemSetting, TrainingVideo, UserProfile

DEFAULT_PASSWORD = "carmel2026"

DEPARTMENTS = [
    ("rh", "Recursos Humanos & Cultura"),
    ("recepcao", "Recepção & Concierge"),
    ("governanca", "Governança & Rouparia"),
    ("alimentos_bebidas", "Alimentos & Bebidas"),
    ("experiencias", "Lazer & Experiências"),
    ("manutencao", "Manutenção & Engenharia"),
]

USERS = [
    # username, email, first, last, role, dept_code, superuser
    ("admin", "admin@carmel.com.br", "Administrador", "Carmel", UserProfile.ROLE_ADMIN, None, True),
    ("gestor.rh", "gestor.rh@carmel.com.br", "Mariana", "Albuquerque", UserProfile.ROLE_GESTOR, "rh", False),
    ("colab.governanca", "camareira@carmel.com.br", "Clara", "Menezes", UserProfile.ROLE_COLABORADOR, "governanca", False),
]

SAMPLE_VIDEOS = [
    ("rh", "Manual de Boas-Vindas & Cultura Carmel", "Manual_Integracao_Carmel_2026.pdf",
     "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4",
     "https://images.unsplash.com/photo-1566073771259-6a8506099945?w=800&auto=format&fit=crop&q=80",
     "Olá, equipe! Sejam muito bem-vindos à família Carmel. Nosso propósito é transformar momentos simples em memórias inesquecíveis para os hóspedes.",
     145.0),
    ("recepcao", "Protocolo de Check-in Exclusivo VIP", "POP_Recepcao_VIP.docx",
     "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ElephantsDream.mp4",
     "https://images.unsplash.com/photo-1582719508461-905c673771fd?w=800&auto=format&fit=crop&q=80",
     "Olá, equipe de Recepção. O protocolo VIP exige a recepção calorosa, entrega de toalhas perfumadas e drink de boas-vindas com agilidade no cadastro.",
     98.0),
    ("governanca", "Padrão de Higienização e Cama dos Sonhos", "POP_Governanca_Suites.pdf",
     "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4",
     "https://images.unsplash.com/photo-1618773928121-c32242e63f39?w=800&auto=format&fit=crop&q=80",
     "Bem-vindos ao treinamento de Governança. Nossa Cama dos Sonhos é a marca do aconchego Carmel. Vamos repassar a técnica dos lençóis de algodão egípcio.",
     120.0),
]


class Command(BaseCommand):
    help = "Popula o banco com setores, grupos, usuários de teste e vídeos de exemplo (idempotente)."

    @transaction.atomic
    def handle(self, *args, **options):
        depts = {}
        for code, name in DEPARTMENTS:
            dept, created = Department.objects.get_or_create(code=code, defaults={'name': name})
            depts[code] = dept
            if created:
                self.stdout.write(f"[OK] Setor criado: {name}")

        for username, email, first, last, role, dept_code, superuser in USERS:
            if User.objects.filter(username=username).exists():
                continue
            create = User.objects.create_superuser if superuser else User.objects.create_user
            user = create(username, email, DEFAULT_PASSWORD, first_name=first, last_name=last)
            profile = user.profile
            profile.role = role
            profile.department = depts.get(dept_code)
            profile.save()
            self.stdout.write(self.style.SUCCESS(f"[OK] Usuário criado: {username} / {DEFAULT_PASSWORD}"))

        if not TrainingVideo.objects.exists():
            for code, title, fname, v_url, thumb, script, dur in SAMPLE_VIDEOS:
                TrainingVideo.objects.create(
                    department=depts[code], title=title, file_name=fname,
                    drive_file_id=f"sample_{code}", status=TrainingVideo.Status.COMPLETED,
                    status_message='Vídeo de exemplo', video_url=v_url, thumbnail_url=thumb,
                    script_text=script, duration_seconds=dur, completed_at=timezone.now(),
                )
            self.stdout.write(self.style.SUCCESS("[OK] Treinamentos de exemplo cadastrados."))

        # Só cria as configurações se ainda não existirem — nunca sobrescreve chaves já salvas.
        SystemSetting.objects.get_or_create(
            key="heygen_mock_mode",
            defaults={'value': '', 'description': "true/false. Vazio = usa HEYGEN_MOCK_MODE do .env"},
        )
        SystemSetting.objects.get_or_create(
            key="heygen_api_key",
            defaults={'value': '', 'description': "Chave da HeyGen. Vazio = usa HEYGEN_API_KEY do .env"},
        )
        self.stdout.write(self.style.SUCCESS("[OK] Seed concluído."))
