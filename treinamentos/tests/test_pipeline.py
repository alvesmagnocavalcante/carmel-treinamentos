"""Leitura do documento, revisão do roteiro e espera pelo vídeo."""

from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from ..models import SystemSetting, TrainingVideo, UserProfile
from ..services.document_parser import clean_script
from ..services.pipeline import process_training_video
from ..services.storage import safe_filename
from .base import TMP, BaseTestCase, make_user


class PipelineTests(BaseTestCase):
    def make_job(self, content=b"Passo 1. Cumprimente o hospede. Passo 2. Ofereca ajuda."):
        dest = TMP / "temp_docs" / "job.txt"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        return TrainingVideo.objects.create(department=self.rh, title="POP", file_name="job.txt", source_path=str(dest))

    def test_missing_file_fails_gracefully(self):
        job = TrainingVideo.objects.create(department=self.rh, title="X", file_name="nao_existe.pdf")
        process_training_video(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")

    @override_settings(REQUIRE_SCRIPT_REVIEW=False)
    def test_script_over_heygen_limit_fails(self):
        job = self.make_job(content=("Frase de teste. " * 400).encode())
        process_training_video(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertIn("limite da HeyGen", job.status_message)

    def test_empty_db_setting_falls_back_to_env(self):
        SystemSetting.objects.create(key="google_service_account_file", value="")
        self.assertEqual(SystemSetting.get_val("google_service_account_file", "from-env"), "from-env")


class HelperTests(TestCase):
    def test_safe_filename(self):
        self.assertEqual(safe_filename("../../etc/passwd"), "passwd")
        self.assertEqual(safe_filename("C:\\temp\\Manual RH.pdf"), "Manual_RH.pdf")

    def test_clean_script_removes_markdown_and_bullets(self):
        raw = "# Título\n\n- **Olá**, equipe\n* Passo `1`\n\n\n\nFim"
        self.assertEqual(clean_script(raw), "Título\n\nOlá, equipe\nPasso 1\n\nFim")

    def test_clean_script_removes_item_numbering_but_keeps_numbers_in_sentences(self):
        raw = "1. Cumprimente\n2) Ofereça ajuda\n3.2 Despedida\na) Sorria\n10 pessoas chegam em 2024."
        expected = "Cumprimente\nOfereça ajuda\nDespedida\nSorria\n10 pessoas chegam em 2024."
        self.assertEqual(clean_script(raw), expected)


class ScriptReviewTests(BaseTestCase):
    def make_waiting(self, script="Olá, equipe."):
        return TrainingVideo.objects.create(
            department=self.rh, title="POP", file_name="p.txt",
            status="AWAITING_REVIEW", script_text=script,
        )

    def test_pipeline_stops_for_review(self):
        dest = TMP / "temp_docs" / "rev.txt"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"1. Cumprimente o hospede.")
        job = TrainingVideo.objects.create(department=self.rh, title="POP", file_name="rev.txt", source_path=str(dest))
        process_training_video(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, "AWAITING_REVIEW")
        self.assertEqual(job.script_text, "Cumprimente o hospede.")

    @mock.patch("treinamentos.views.start_pipeline_async")
    def test_script_over_limit_is_not_approved(self, start):
        job = self.make_waiting()
        self.client.force_login(self.gestor)
        resp = self.client.post(reverse("review_script", args=[job.id]), {"script": "a" * 5001})
        self.assertEqual(resp.status_code, 200)
        job.refresh_from_db()
        self.assertEqual(job.status, "AWAITING_REVIEW")
        start.assert_not_called()

    @mock.patch("treinamentos.views.start_pipeline_async")
    def test_review_access_control(self, start):
        job = self.make_waiting()
        url = reverse("review_script", args=[job.id])
        self.client.force_login(self.colab)
        self.assertEqual(self.client.get(url).status_code, 403)
        # gestor de outro setor não enxerga o vídeo
        self.client.force_login(make_user("gestor2", UserProfile.ROLE_GESTOR, self.gov))
        self.assertEqual(self.client.post(url, {"script": "x"}).status_code, 404)
        start.assert_not_called()

    @mock.patch("treinamentos.views.start_pipeline_async")
    def test_cannot_review_twice(self, start):
        job = self.make_waiting()
        job.status = "COMPLETED"
        job.save()
        self.client.force_login(self.gestor)
        resp = self.client.post(reverse("review_script", args=[job.id]), {"script": "x"})
        self.assertRedirects(resp, reverse("queue"))
        start.assert_not_called()


class AwaitingVideoTests(BaseTestCase):
    def make_waiting(self, dept=None, status="AWAITING_VIDEO"):
        return TrainingVideo.objects.create(
            department=dept or self.rh, title="POP Vinho", file_name="p.txt",
            status=status, script_text="Olá, equipe. Servimos o vinho com carinho.",
        )

    @override_settings(REQUIRE_SCRIPT_REVIEW=False)
    def test_pipeline_waits_for_video(self):
        dest = TMP / "temp_docs" / "man.txt"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"Cumprimente o hospede.")
        job = TrainingVideo.objects.create(department=self.rh, title="POP", file_name="man.txt", source_path=str(dest))
        process_training_video(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, "AWAITING_VIDEO")
        self.assertIn("Aguardando a geração do vídeo", job.status_message)

    @mock.patch("treinamentos.views.start_pipeline_async")
    def test_approval_waits_for_the_video(self, start):
        job = self.make_waiting(status="AWAITING_REVIEW")
        self.client.force_login(self.gestor)
        resp = self.client.post(reverse("review_script", args=[job.id]), {"script": "Texto aprovado."})
        self.assertRedirects(resp, reverse("queue"))
        job.refresh_from_db()
        self.assertEqual((job.status, job.script_text), ("AWAITING_VIDEO", "Texto aprovado."))
        start.assert_not_called()

    def test_queue_shows_attach_button_to_managers_only(self):
        job = self.make_waiting()
        url = reverse("attach_video", args=[job.id])
        self.client.force_login(self.gestor)
        self.assertIn(url, self.client.get(reverse("queue")).content.decode())
        self.client.force_login(self.admin)
        self.assertIn("Aguardando vídeo", self.client.get(reverse("queue")).content.decode())

    def test_attach_access_control_and_status(self):
        job = self.make_waiting()
        url = reverse("attach_video", args=[job.id])
        self.client.force_login(self.colab)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(make_user("gestor2", UserProfile.ROLE_GESTOR, self.gov))
        self.assertEqual(self.client.get(url).status_code, 404)  # outro setor
        self.client.force_login(self.gestor)
        self.assertEqual(self.client.get(url).status_code, 200)
        job.status = "COMPLETED"
        job.save()
        self.assertRedirects(self.client.get(url), reverse("queue"))

    @mock.patch("treinamentos.services.pipeline.GoogleDriveService.upload_video_file", return_value="drv-7")
    def test_attach_video_publishes_and_saves_in_drive(self, upload):
        job = self.make_waiting()
        self.client.force_login(self.gestor)
        f = SimpleUploadedFile("v.mp4", b"0" * 100, content_type="video/mp4")
        resp = self.client.post(reverse("attach_video", args=[job.id]), {"file": f})
        self.assertRedirects(resp, reverse("queue"))
        job.refresh_from_db()
        self.assertEqual((job.status, job.drive_video_id), ("COMPLETED", "drv-7"))
        self.assertEqual(job.play_url, reverse("stream_video", args=[job.id]))
        upload.assert_called_once()

    @mock.patch("treinamentos.services.pipeline.GoogleDriveService.upload_video_file")
    def test_attach_rejects_wrong_format_and_oversize(self, upload):
        job = self.make_waiting()
        self.client.force_login(self.gestor)
        url = reverse("attach_video", args=[job.id])
        self.client.post(url, {"file": SimpleUploadedFile("v.avi", b"0", content_type="video/avi")})
        with override_settings(MAX_VIDEO_MB=0):
            self.client.post(url, {"file": SimpleUploadedFile("v.mp4", b"0" * 10, content_type="video/mp4")})
        job.refresh_from_db()
        self.assertEqual(job.status, "AWAITING_VIDEO")
        upload.assert_not_called()

    @mock.patch("treinamentos.services.pipeline.GoogleDriveService.upload_video_file", side_effect=RuntimeError("sem Drive"))
    def test_attach_keeps_waiting_when_drive_fails(self, upload):
        job = self.make_waiting()
        self.client.force_login(self.gestor)
        resp = self.client.post(
            reverse("attach_video", args=[job.id]),
            {"file": SimpleUploadedFile("v.mp4", b"0" * 10, content_type="video/mp4")},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Não foi possível salvar no Drive")
        job.refresh_from_db()
        self.assertEqual(job.status, "AWAITING_VIDEO")
