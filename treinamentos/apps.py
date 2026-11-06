from django.apps import AppConfig
from django.contrib.admin.apps import AdminConfig


class TreinamentosConfig(AppConfig):
    name = 'treinamentos'


class CarmelAdminConfig(AdminConfig):
    """Usa o painel próprio (treinamentos/admin_site.py) no lugar do Admin padrão do Django."""
    default_site = 'treinamentos.admin_site.CarmelAdminSite'
