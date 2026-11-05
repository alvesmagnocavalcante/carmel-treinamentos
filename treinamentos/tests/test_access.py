"""Acesso por perfil e setor, login e telas básicas."""

from django.urls import reverse

from ..models import VideoProgress
from .base import BaseTestCase


class AccessControlTests(BaseTestCase):
    def titles(self, response):
        return {v.title for v in response.context["videos"]}

    def test_login_required(self):
        self.assertRedirects(self.client.get(reverse("home")), f"{reverse('login')}?next=/")

    def test_colaborador_sees_only_own_department(self):
        self.client.force_login(self.colab)
        self.assertEqual(self.titles(self.client.get(reverse("home"))), {"Vídeo Gov"})
        # tentar forçar outro setor pela URL não vaza conteúdo
        self.assertEqual(self.titles(self.client.get(reverse("home") + "?setor=rh")), {"Vídeo Gov"})

    def test_colaborador_without_department_sees_nothing(self):
        self.client.force_login(self.sem_setor)
        self.assertEqual(self.titles(self.client.get(reverse("home"))), set())

    def test_gestor_sees_only_own_department(self):
        self.client.force_login(self.gestor)
        self.assertEqual(self.titles(self.client.get(reverse("home"))), {"Vídeo RH"})
        jobs = self.client.get(reverse("queue")).context["jobs"]
        self.assertEqual({j.title for j in jobs}, {"Vídeo RH"})

    def test_admin_sees_everything_and_can_filter(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.titles(self.client.get(reverse("home"))), {"Vídeo RH", "Vídeo Gov"})
        self.assertEqual(self.titles(self.client.get(reverse("home") + "?setor=rh")), {"Vídeo RH"})

    def test_colaborador_cannot_sync(self):
        self.client.force_login(self.colab)
        self.assertEqual(self.client.post(reverse("sync_drive")).status_code, 403)

    def test_sync_requires_post(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("sync_drive")).status_code, 405)

    def test_register_view_only_for_visible_videos(self):
        self.client.force_login(self.colab)
        self.assertEqual(self.client.post(reverse("register_view", args=[self.v_rh.id])).status_code, 404)
        self.client.post(reverse("register_view", args=[self.v_gov.id]))
        self.assertFalse(VideoProgress.objects.get(user=self.colab, video=self.v_gov).completed)
        self.client.post(reverse("register_view", args=[self.v_gov.id]), {"completed": "1"})
        self.assertTrue(VideoProgress.objects.get(user=self.colab, video=self.v_gov).completed)

    def test_script_is_not_rendered_as_html(self):
        self.v_gov.script_text = '<img src=x onerror="alert(1)">'
        self.v_gov.save()
        self.client.force_login(self.colab)
        html = self.client.get(reverse("home")).content.decode()
        self.assertNotIn('<img src=x onerror', html)

    def test_logout_requires_post(self):
        self.client.force_login(self.colab)
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.assertRedirects(self.client.post(reverse("logout")), reverse("login"))

    def test_login_redirects_to_safe_next_only(self):
        resp = self.client.post(reverse("login"), {"username": "colab", "password": "x123456", "next": "https://evil.com/"})
        self.assertRedirects(resp, reverse("home"))

    def test_admin_pages_render(self):
        self.client.force_login(self.admin)
        for url in ("/admin/", "/admin/treinamentos/trainingvideo/", "/admin/treinamentos/systemsetting/", "/admin/auth/user/"):
            self.assertEqual(self.client.get(url).status_code, 200, url)
