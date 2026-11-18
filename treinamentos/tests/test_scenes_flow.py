"""Cenas no pipeline e na tela de revisão: marcação, imagem ausente, limite e compatibilidade."""

from django.test import override_settings
from django.urls import reverse

from ..models import DriveImage, TrainingVideo
from ..services.pipeline import process_training_video
from .base import TMP, BaseTestCase


class ScenePipelineTests(BaseTestCase):
    def job(self, content: bytes):
        dest = TMP / "temp_docs" / "cenas.txt"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        return TrainingVideo.objects.create(department=self.rh, title="POP", file_name="cenas.txt", source_path=str(dest))

    def test_marked_document_becomes_scenes_and_joined_script(self):
        job = self.job("Abertura.\n[IMAGEM: piscina.png]\nA piscina.\n[IMAGEM: bar.jpg]\nO bar.".encode())
        process_training_video(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, "AWAITING_REVIEW")
        self.assertEqual([(s["ordem"], s["imagem"]) for s in job.scenes], [(1, ""), (2, "piscina.png"), (3, "bar.jpg")])
        self.assertEqual(job.script_text, "Abertura.\n\nA piscina.\n\nO bar.")
        self.assertNotIn("IMAGEM", job.script_text)

    def test_document_without_markers_is_unchanged(self):
        job = self.job(b"1. Cumprimente o hospede.\n2. Ofereca ajuda.")
        process_training_video(job.id)
        job.refresh_from_db()
        self.assertEqual(job.scenes, [])  # nada novo é guardado: comportamento de sempre
        self.assertEqual(job.script_text, "Cumprimente o hospede.\nOfereca ajuda.")
        self.assertEqual(job.status, "AWAITING_REVIEW")

    def test_limit_counts_only_the_spoken_text(self):
        body = "Frase de teste. " * 150  # 2400 caracteres falados por cena
        job = self.job(f"[IMAGEM: a.png]\n{body}\n[IMAGEM: b.png]\n{body}".encode())
        process_training_video(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, "AWAITING_REVIEW")  # 4800 falados: cabe, mesmo com as marcações no arquivo

    @override_settings(REQUIRE_SCRIPT_REVIEW=False)
    def test_without_review_a_missing_image_fails_with_a_clear_message(self):
        job = self.job(b"[IMAGEM: sumiu.png]\nTexto.")
        process_training_video(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertIn("sumiu.png", job.status_message)

    @override_settings(REQUIRE_SCRIPT_REVIEW=False)
    def test_without_review_and_with_the_image_it_waits_for_the_video(self):
        DriveImage.objects.create(department=self.rh, name="ok.png", drive_file_id="d1", mime_type="image/png")
        job = self.job(b"[IMAGEM: OK.png]\nTexto.")
        process_training_video(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, "AWAITING_VIDEO")


class SceneReviewTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.video = TrainingVideo.objects.create(
            department=self.rh, title="POP", file_name="p.txt", status="AWAITING_REVIEW", script_text="Olá, equipe.",
        )
        self.url = reverse("review_script", args=[self.video.id])
        self.client.force_login(self.gestor)

    def post(self, **data):
        return self.client.post(self.url, data)

    def test_legacy_video_shows_one_scene_with_its_script(self):
        resp = self.client.get(self.url)
        self.assertEqual([s["texto"] for s in resp.context["scenes"]], ["Olá, equipe."])
        self.assertContains(resp, 'name="scene_text"')
        self.assertContains(resp, 'name="scene_image"')

    def test_review_page_lists_the_sector_images_and_flags_missing_ones(self):
        DriveImage.objects.create(department=self.rh, name="piscina.png", drive_file_id="d1")
        DriveImage.objects.create(department=self.gov, name="outra.png", drive_file_id="d2")  # outro setor: não aparece
        self.video.scenes = [{"ordem": 1, "texto": "Um.", "imagem": "piscina.png"},
                             {"ordem": 2, "texto": "Dois.", "imagem": "fantasma.png"}]
        self.video.save()
        resp = self.client.get(self.url)
        self.assertEqual(resp.context["image_names"], ["piscina.png"])
        problems = [s["problema"] for s in resp.context["scenes"]]
        self.assertEqual(problems[0], "")
        self.assertIn("fantasma.png", problems[1])
        self.assertContains(resp, "não encontrada na pasta Imagens")

    def test_approval_with_images_stores_the_scenes(self):
        DriveImage.objects.create(department=self.rh, name="piscina.png", drive_file_id="d1")
        resp = self.client.post(self.url, {
            "scene_text": ["Boas-vindas.", "A piscina."], "scene_image": ["", "Piscina.PNG"],
        })
        self.assertRedirects(resp, reverse("queue"))
        self.video.refresh_from_db()
        self.assertEqual(self.video.status, "AWAITING_VIDEO")
        self.assertEqual(self.video.scenes, [
            {"ordem": 1, "texto": "Boas-vindas.", "imagem": ""},
            {"ordem": 2, "texto": "A piscina.", "imagem": "Piscina.PNG"},
        ])
        self.assertEqual(self.video.script_text, "Boas-vindas.\n\nA piscina.")

    def test_missing_image_blocks_the_approval(self):
        resp = self.client.post(self.url, {"scene_text": ["Texto."], "scene_image": ["sumiu.png"]})
        self.assertEqual(resp.status_code, 200)
        self.video.refresh_from_db()
        self.assertEqual(self.video.status, "AWAITING_REVIEW")
        self.assertContains(resp, "sumiu.png")
        self.assertContains(resp, 'value="sumiu.png"')  # o que a pessoa digitou não se perde

    def test_oversized_and_wrong_format_images_block_the_approval(self):
        DriveImage.objects.create(department=self.rh, name="enorme.png", drive_file_id="d1", too_large=True)
        for name in ("enorme.png", "manual.pdf"):
            resp = self.client.post(self.url, {"scene_text": ["Texto."], "scene_image": [name]})
            self.assertEqual(resp.status_code, 200, name)
        self.video.refresh_from_db()
        self.assertEqual(self.video.status, "AWAITING_REVIEW")

    def test_removing_the_image_lets_the_approval_go_through(self):
        resp = self.client.post(self.url, {"scene_text": ["Texto."], "scene_image": [""]})
        self.assertRedirects(resp, reverse("queue"))
        self.video.refresh_from_db()
        self.assertEqual(self.video.scenes, [])  # uma cena sem imagem é o roteiro de sempre
        self.assertEqual(self.video.script_text, "Texto.")

    def test_blank_scenes_disappear_and_scene_with_image_but_no_text_is_an_error(self):
        resp = self.client.post(self.url, {"scene_text": ["Texto.", "  "], "scene_image": ["", ""]})
        self.assertRedirects(resp, reverse("queue"))
        self.video.refresh_from_db()
        self.assertEqual(self.video.script_text, "Texto.")
        self.video.set_status("AWAITING_REVIEW")
        DriveImage.objects.create(department=self.rh, name="a.png", drive_file_id="d1")
        resp = self.client.post(self.url, {"scene_text": ["Texto.", ""], "scene_image": ["", "a.png"]})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "sem texto")

    def test_limit_applies_to_the_total_spoken_text(self):
        resp = self.client.post(self.url, {"scene_text": ["a" * 2600, "b" * 2600], "scene_image": ["", ""]})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "limite da HeyGen")
        self.video.refresh_from_db()
        self.assertEqual(self.video.status, "AWAITING_REVIEW")

    def test_old_single_field_still_works_and_accepts_markers(self):
        DriveImage.objects.create(department=self.rh, name="a.png", drive_file_id="d1")
        resp = self.client.post(self.url, {"script": "Um.\n[IMAGEM: a.png]\nDois."})
        self.assertRedirects(resp, reverse("queue"))
        self.video.refresh_from_db()
        self.assertEqual([s["imagem"] for s in self.video.scenes], ["", "a.png"])
