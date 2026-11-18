"""Modelo de cenas: vídeo sem cenas gravadas continua sendo uma cena só; imagens do Drive por nome."""

from ..models import DriveImage, TrainingVideo
from .base import BaseTestCase


class SceneModelTests(BaseTestCase):
    def make(self, **kw):
        return TrainingVideo.objects.create(department=self.rh, title="POP", file_name="p.txt", **kw)

    def test_video_without_scenes_is_one_scene_with_the_script(self):
        video = self.make(script_text="Olá, equipe.")
        self.assertEqual(video.scenes, [])
        self.assertEqual(video.scene_list, [{"ordem": 1, "texto": "Olá, equipe.", "imagem": ""}])
        self.assertFalse(video.has_images)

    def test_empty_script_has_no_scenes(self):
        self.assertEqual(self.make().scene_list, [])

    def test_saved_scenes_are_returned_as_they_are(self):
        scenes = [{"ordem": 1, "texto": "Um.", "imagem": "a.png"}, {"ordem": 2, "texto": "Dois.", "imagem": ""}]
        video = self.make(script_text="Um.\n\nDois.", scenes=scenes)
        video.refresh_from_db()
        self.assertEqual(video.scene_list, scenes)
        self.assertTrue(video.has_images)

    def test_drive_image_key_ignores_accent_and_case(self):
        img = DriveImage.objects.create(department=self.rh, name="Área Externa.PNG", drive_file_id="d1")
        self.assertEqual(img.name_key, "area externa.png")
        self.assertTrue(DriveImage.objects.filter(department=self.rh, name_key="area externa.png").exists())
