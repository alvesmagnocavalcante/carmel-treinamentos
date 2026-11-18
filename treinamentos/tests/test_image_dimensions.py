"""Dimensões das imagens: guardadas pela sincronização e usadas para avisar sobre foto em pé."""

from unittest import mock

from django.urls import reverse

from ..models import DriveImage, TrainingVideo
from ..services.scenes import image_notice
from .base import BaseTestCase
from .fakes import FakeDrive


class ImageDimensionsTests(BaseTestCase):
    def img(self, name, w, h):
        return DriveImage.objects.create(department=self.rh, name=name, drive_file_id=f"d-{name}", width=w, height=h)

    def test_sync_stores_the_dimensions_given_by_the_drive(self):
        from ..services.drive_service import GoogleDriveService
        self.rh.drive_folder_id = "root"
        self.rh.save()
        drive = FakeDrive()
        imagens = drive.add("Imagens", "root", FakeDrive.FOLDER)
        drive.add("horizontal.jpg", imagens, "image/jpeg", size=1000, dims=(4000, 2250))
        drive.add("sem-medidas.png", imagens, "image/png", size=1000)
        with mock.patch.object(GoogleDriveService, "get_drive_client", return_value=drive):
            GoogleDriveService.scan_all_departments([self.rh])
        h = DriveImage.objects.get(name="horizontal.jpg")
        self.assertEqual((h.width, h.height), (4000, 2250))
        s = DriveImage.objects.get(name="sem-medidas.png")
        self.assertEqual((s.width, s.height), (0, 0))

    def test_landscape_photo_gets_no_notice(self):
        self.img("a.jpg", 4000, 2250)  # 16:9
        self.img("b.jpg", 3000, 2000)  # 3:2
        self.assertEqual(image_notice(self.rh, "a.jpg"), "")
        self.assertEqual(image_notice(self.rh, "b.jpg"), "")

    def test_portrait_and_square_photos_get_a_crop_notice(self):
        self.img("pe.jpg", 2000, 3000)
        self.img("quadrada.png", 2000, 2000)
        self.img("quatro-tres.jpg", 2000, 1500)
        for name in ("pe.jpg", "quadrada.png", "quatro-tres.jpg"):
            self.assertIn("cortada", image_notice(self.rh, name), name)

    def test_unknown_size_or_missing_image_gives_no_notice(self):
        self.img("sem.png", 0, 0)
        self.assertEqual(image_notice(self.rh, "sem.png"), "")
        self.assertEqual(image_notice(self.rh, "nao-existe.png"), "")
        self.assertEqual(image_notice(self.rh, ""), "")

    def test_review_shows_the_notice_but_does_not_block_the_approval(self):
        self.img("pe.jpg", 2000, 3000)
        video = TrainingVideo.objects.create(
            department=self.rh, title="POP", file_name="p.txt", status="AWAITING_REVIEW", script_text="Texto.",
            scenes=[{"ordem": 1, "texto": "Texto.", "imagem": "pe.jpg"}],
        )
        self.client.force_login(self.gestor)
        url = reverse("review_script", args=[video.id])
        self.assertContains(self.client.get(url), "será cortada")
        resp = self.client.post(url, {"scene_text": ["Texto."], "scene_image": ["pe.jpg"]})
        self.assertRedirects(resp, reverse("queue"))
        video.refresh_from_db()
        self.assertEqual(video.status, "AWAITING_VIDEO")
