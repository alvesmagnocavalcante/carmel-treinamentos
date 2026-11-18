"""Tela de revisão com imagem animada: escolher animar, escrever o movimento e respeitar o limite."""

from django.test import override_settings
from django.urls import reverse

from ..models import DriveImage, TrainingVideo
from .base import BaseTestCase


class AnimationReviewTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        for name in ("a.png", "b.png", "c.png"):
            DriveImage.objects.create(department=self.rh, name=name, drive_file_id=f"d-{name}")
        self.video = TrainingVideo.objects.create(
            department=self.rh, title="POP", file_name="p.txt", status="AWAITING_REVIEW", script_text="Texto.",
        )
        self.url = reverse("review_script", args=[self.video.id])
        self.client.force_login(self.gestor)

    def approve(self, **data):
        return self.client.post(self.url, data)

    def test_page_offers_the_animation_choice_and_the_limit(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, 'name="scene_animar"')
        self.assertContains(resp, "Animar a imagem (IA)")
        self.assertContains(resp, 'name="scene_movimento"')
        self.assertEqual(resp.context["max_animated"], 4)

    def test_animated_scene_is_stored_with_its_movement(self):
        resp = self.approve(scene_text=["Abertura.", "A piscina."], scene_image=["", "a.png"],
                            scene_animar=["0", "1"], scene_movimento=["", "brisa leve nas palmeiras"])
        self.assertRedirects(resp, reverse("queue"))
        self.video.refresh_from_db()
        self.assertEqual(self.video.scenes, [
            {"ordem": 1, "texto": "Abertura.", "imagem": ""},
            {"ordem": 2, "texto": "A piscina.", "imagem": "a.png", "animar": True, "movimento": "brisa leve nas palmeiras"},
        ])

    def test_not_animated_scene_has_no_new_keys(self):
        self.approve(scene_text=["Um.", "Dois."], scene_image=["a.png", "b.png"],
                     scene_animar=["0", "0"], scene_movimento=["", ""])
        self.video.refresh_from_db()
        self.assertTrue(all("animar" not in s and "movimento" not in s for s in self.video.scenes))

    def test_animating_without_an_image_blocks_the_approval(self):
        resp = self.approve(scene_text=["Texto."], scene_image=[""], scene_animar=["1"], scene_movimento=[""])
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "pede animação mas não tem imagem")
        self.video.refresh_from_db()
        self.assertEqual(self.video.status, "AWAITING_REVIEW")

    @override_settings(MAX_ANIMATED_SCENES=1)
    def test_too_many_animated_scenes_block_the_approval(self):
        resp = self.approve(scene_text=["Um.", "Dois."], scene_image=["a.png", "b.png"],
                            scene_animar=["1", "1"], scene_movimento=["", ""])
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "máximo por vídeo é 1")
        self.video.refresh_from_db()
        self.assertEqual(self.video.status, "AWAITING_REVIEW")

    def test_saved_animation_is_shown_again_on_the_page(self):
        self.video.scenes = [{"ordem": 1, "texto": "A piscina.", "imagem": "a.png", "animar": True, "movimento": "zoom lento"}]
        self.video.save()
        html = self.client.get(self.url).content.decode()
        self.assertIn('value="zoom lento"', html)
        self.assertIn('<option value="1" selected>', html)

    def test_movement_text_is_capped_and_escaped(self):
        self.approve(scene_text=["Texto."], scene_image=["a.png"], scene_animar=["1"],
                     scene_movimento=["<b>x</b>" + "y" * 900])
        self.video.refresh_from_db()
        self.assertEqual(len(self.video.scenes[0]["movimento"]), 500)
        html = self.client.get(self.url).content.decode()
        self.assertNotIn("<b>x</b>yyy", html)  # escapado, nunca como HTML

    def test_old_single_field_accepts_the_animate_marker(self):
        resp = self.approve(script="Um.\n[IMAGEM: a.png | animar: zoom lento]\nDois.")
        self.assertRedirects(resp, reverse("queue"))
        self.video.refresh_from_db()
        self.assertEqual(self.video.scenes[1]["movimento"], "zoom lento")
