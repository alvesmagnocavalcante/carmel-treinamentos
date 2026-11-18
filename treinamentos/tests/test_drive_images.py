"""Subpasta Imagens do Drive: a sincronização cadastra as imagens e o roteiro as acha pelo nome."""

from unittest import mock

from django.test import override_settings

from ..models import DriveImage
from ..services.scenes import find_image, image_problem
from .base import BaseTestCase
from .fakes import FakeDrive


class DriveImagesSyncTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        from ..services.drive_service import GoogleDriveService
        self.svc = GoogleDriveService
        self.rh.drive_folder_id = "root"
        self.rh.save()
        self.drive = FakeDrive()
        self.imagens = self.drive.add("Imagens", "root", FakeDrive.FOLDER)

    def scan(self):
        with mock.patch.object(self.svc, "get_drive_client", return_value=self.drive):
            return self.svc.scan_all_departments([self.rh])

    def names(self):
        return sorted(DriveImage.objects.filter(department=self.rh).values_list("name", flat=True))

    def test_png_jpg_and_webp_are_registered_and_other_files_are_ignored(self):
        self.drive.add("piscina.png", self.imagens, "image/png", size=1000)
        self.drive.add("bar.JPG", self.imagens, "image/jpeg", size=1000)
        self.drive.add("recepcao.webp", self.imagens, "image/webp", size=1000)
        self.drive.add("manual.pdf", self.imagens, "application/pdf", size=1000)
        self.drive.add("animacao.gif", self.imagens, "image/gif", size=1000)
        result = self.scan()
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["images"], 3)
        self.assertEqual(self.names(), ["bar.JPG", "piscina.png", "recepcao.webp"])

    def test_image_is_found_by_name_ignoring_accent_and_case(self):
        self.drive.add("Área Externa.PNG", self.imagens, "image/png", size=1000)
        self.scan()
        self.assertEqual(find_image(self.rh, "area externa.png").name, "Área Externa.PNG")
        self.assertIsNone(find_image(self.rh, "outra.png"))
        self.assertIsNone(find_image(self.gov, "area externa.png"))  # outro setor

    def test_second_scan_changes_nothing(self):
        self.drive.add("piscina.png", self.imagens, "image/png", size=1000)
        self.assertEqual(self.scan()["images"], 1)
        self.assertEqual(self.scan()["images"], 0)
        self.assertEqual(DriveImage.objects.count(), 1)

    def test_renamed_resized_and_removed_files_follow_the_drive(self):
        keep = self.drive.add("a.png", self.imagens, "image/png", size=1000)
        gone = self.drive.add("b.png", self.imagens, "image/png", size=1000)
        self.scan()
        self.drive.items[keep]["name"] = "novo.png"
        del self.drive.items[gone]
        self.assertEqual(self.scan()["images"], 1)
        self.assertEqual(self.names(), ["novo.png"])
        self.assertEqual(DriveImage.objects.get().name_key, "novo.png")

    @override_settings(MAX_IMAGE_MB=1)
    def test_oversized_image_is_registered_as_too_large(self):
        self.drive.add("enorme.png", self.imagens, "image/png", size=2 * 1024 * 1024)
        self.drive.add("ok.png", self.imagens, "image/png", size=1024)
        self.scan()
        self.assertTrue(DriveImage.objects.get(name="enorme.png").too_large)
        self.assertFalse(DriveImage.objects.get(name="ok.png").too_large)
        self.assertIn("limite de 1 MB", image_problem(self.rh, "enorme.png"))
        self.assertEqual(image_problem(self.rh, "ok.png"), "")

    def test_image_problems_have_clear_messages(self):
        self.assertEqual(image_problem(self.rh, ""), "")
        self.assertIn("não encontrada", image_problem(self.rh, "sumiu.png"))
        self.assertIn("png, jpg ou webp", image_problem(self.rh, "manual.pdf"))

    def test_images_folder_is_created_with_the_others_and_not_duplicated(self):
        drive = FakeDrive()
        with mock.patch.object(self.svc, "get_drive_client", return_value=drive):
            self.svc.scan_all_departments([self.rh])
            self.svc.scan_all_departments([self.rh])
        names = sorted(v["name"] for v in drive.items.values() if "root" in v["parents"])
        self.assertEqual(names, ["Imagens", "Roteiros", "Vídeos"])

    def test_sync_message_mentions_images(self):
        from django.urls import reverse
        self.drive.add("piscina.png", self.imagens, "image/png", size=1000)
        self.client.force_login(self.gestor)
        with mock.patch.object(self.svc, "get_drive_client", return_value=self.drive):
            data = self.client.post(reverse("sync_drive")).json()
        self.assertEqual(data["status"], "success")
        self.assertIn("1 imagem(ns)", data["message"])
