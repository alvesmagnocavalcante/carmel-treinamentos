import os

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from treinamentos.models import UserProfile
from treinamentos.services import humand


class Command(BaseCommand):
    help = (
        "Dá acesso de administrador (painel /admin e todos os setores) a quem já tem conta. "
        "Sem argumentos, lê a variável ADMIN_LOGINS (CPFs ou usuários separados por vírgula). "
        "Não cria contas e nunca falha o start: quem não existe ainda é só avisado."
    )

    def add_arguments(self, parser):
        parser.add_argument("logins", nargs="*", help="CPF (com ou sem pontos) ou nome de usuário")

    def handle(self, *args, **options):
        logins = options["logins"] or [x for x in os.getenv("ADMIN_LOGINS", "").replace(";", ",").split(",")]
        for raw in (x.strip() for x in logins):
            if not raw:
                continue
            username = humand.clean_cpf(raw) or raw
            user = User.objects.filter(username__iexact=username).first()
            if user is None:
                self.stdout.write(f"[AVISO] Ainda não há conta para '{raw[:3]}***': a pessoa precisa se cadastrar primeiro.")
                continue
            user.is_active = user.is_staff = user.is_superuser = True
            user.save(update_fields=["is_active", "is_staff", "is_superuser"])
            UserProfile.objects.filter(user=user).update(role=UserProfile.ROLE_ADMIN)
            self.stdout.write(f"[OK] {user.first_name or 'Conta'} agora é administrador.")
