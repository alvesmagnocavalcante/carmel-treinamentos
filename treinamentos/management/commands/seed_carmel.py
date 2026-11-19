import os

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction

from treinamentos.models import Department, UserProfile

DEFAULT_PASSWORD = "carmel2026"

# Os mesmos setores da Humand (e das pastas do Drive); o RH mantém o nome antigo, já configurado em produção.
DEPARTMENTS = [
    ("rh", "Recursos Humanos & Cultura"),
    ("administracao", "Administração"),
    ("almoxarifado", "Almoxarifado"),
    ("bar-e-restaurante", "Bar e Restaurante"),
    ("comercial", "Comercial"),
    ("compras", "Compras"),
    ("contabilidade", "Contabilidade"),
    ("controladoria", "Controladoria"),
    ("cozinha", "Cozinha"),
    ("financeiro", "Financeiro"),
    ("governanca", "Governança"),
    ("logistica", "Logística"),
    ("manutencao", "Manutenção"),
    ("marketing", "Marketing"),
    ("portaria", "Portaria"),
    ("qualidade", "Qualidade"),
    ("recepcao", "Recepção"),
    ("reservas", "Reservas"),
    ("rm", "RM"),
    ("setor-pessoal", "Setor pessoal"),
    ("tecnologia-da-informacao", "Tecnologia da Informação"),
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

        if os.getenv("SEED_DEMO_USERS", "").lower() not in ("1", "true", "yes"):
            self.stdout.write("Usuários de teste não criados (defina SEED_DEMO_USERS=true apenas em ambiente de teste).")
            USERS_TO_CREATE = []
        else:
            USERS_TO_CREATE = USERS

        for username, email, first, last, role, dept_code, superuser in USERS_TO_CREATE:
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
