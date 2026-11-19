from django.contrib.auth.backends import ModelBackend

from .services import humand


class CpfModelBackend(ModelBackend):
    """Login normal do Django, mas o CPF vale com ou sem pontos e traço (portal e /admin/login/)."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        username = (username or "").strip()
        return super().authenticate(request, username=humand.clean_cpf(username) or username, password=password, **kwargs)
