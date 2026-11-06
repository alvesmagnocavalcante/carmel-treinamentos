"""Painel de administração: página inicial com resumo, menu lateral e listas."""

from django.urls import reverse

from ..models import TrainingVideo
from .base import BaseTestCase


class AdminPanelTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        TrainingVideo.objects.create(department=self.rh, title="Em revisão", file_name="r.txt", status="AWAITING_REVIEW")
        TrainingVideo.objects.create(department=self.rh, title="Quebrou", file_name="f.txt", status="FAILED")
        self.client.force_login(self.admin)

    def test_dashboard_shows_counts_by_status(self):
        resp = self.client.get(reverse("admin:index"))
        self.assertEqual(resp.status_code, 200)
        values = {k["label"]: k["value"] for k in resp.context["kpis"]}
        self.assertEqual(values["Vídeos publicados"], 2)
        self.assertEqual(values["Aguardando revisão"], 1)
        self.assertEqual(values["Com falha"], 1)
        self.assertContains(resp, "Olá, ")

    def test_dashboard_warns_about_sectors_without_drive_folder(self):
        self.rh.drive_folder_id = "abc"
        self.rh.save()
        resp = self.client.get(reverse("admin:index"))
        self.assertEqual(resp.context["sectors_without_drive"], 1)  # só a Governança continua sem pasta
        self.assertContains(resp, "sem pasta do Drive")

    def test_navigation_groups_models_with_icons(self):
        resp = self.client.get(reverse("admin:index"))
        titles = [g["title"] for g in resp.context["carmel_nav"]]
        self.assertEqual(titles, ["Pessoas e acessos", "Conteúdo", "Sistema"])
        self.assertContains(resp, 'id="carmel-nav"')
        self.assertContains(resp, "Encerrar sessão")  # conta no menu (no celular o cabeçalho não mostra o usuário)
        self.assertContains(resp, "header-theme")
        # a página de uma lista marca o item ativo do menu
        resp = self.client.get(reverse("admin:treinamentos_trainingvideo_changelist"))
        active = [i["name"] for g in resp.context["carmel_nav"] for i in g["items"] if i["active"]]
        self.assertEqual(active, ["Vídeos de treinamento"])

    def test_video_list_shows_status_badges_and_filters_by_status(self):
        url = reverse("admin:treinamentos_trainingvideo_changelist")
        resp = self.client.get(url)
        self.assertContains(resp, 'class="pill pill-ok"')
        resp = self.client.get(url + "?status__exact=FAILED")
        self.assertContains(resp, "Quebrou")
        self.assertNotContains(resp, "Em revisão")

    def test_forms_open_with_grouped_fields(self):
        video = TrainingVideo.objects.first()
        for url in (
            reverse("admin:treinamentos_trainingvideo_change", args=[video.id]),
            reverse("admin:treinamentos_department_change", args=[self.rh.id]),
            reverse("admin:treinamentos_department_add"),
        ):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_staff_without_permissions_gets_an_empty_but_working_dashboard(self):
        from django.contrib.auth.models import User
        staff = User.objects.create_user("equipe", password="x123456", is_staff=True)
        self.client.force_login(staff)
        resp = self.client.get(reverse("admin:index"))
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("kpis", resp.context)
