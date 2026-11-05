from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction

from treinamentos.models import Department, UserProfile

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

class Command(BaseCommand):
    help = "Popula o banco com setores, grupos, e usuários de teste (idempotente)."

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

        self.stdout.write(self.style.SUCCESS("[OK] Seed concluído."))
