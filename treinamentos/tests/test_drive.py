"""Estrutura de pastas do Drive e publicação dos vídeos pela sincronização."""

from unittest import mock

from django.urls import reverse

from ..models import TrainingVideo
from .base import BaseTestCase
from .fakes import FakeDownloader, FakeDrive, FakeStream


class DriveFolderStructureTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        from ..services.drive_service import GoogleDriveService
        self.svc = GoogleDriveService
        self.rh.drive_folder_id = "root"
        self.rh.save()
        self.drive = FakeDrive()

    def names(self, parent="root"):
        return sorted(v["name"] for v in self.drive.items.values() if parent in v["parents"])

    def test_scan_creates_missing_subfolders_and_reuses_existing_ones(self):
        self.drive.add("videos", "root", FakeDrive.FOLDER)  # sem acento e minúsculo: deve ser reaproveitada
        with mock.patch.object(self.svc, "get_drive_client", return_value=self.drive):
            result = self.svc.scan_all_departments([self.rh])
        self.assertEqual(result["errors"], [])
        self.assertEqual(self.names(), ["Roteiros", "videos"])  # só criou Roteiros, não duplicou Vídeos

    def test_scan_reads_scripts_only_from_roteiros_folder(self):
        roteiros = self.drive.add("Roteiros", "root", FakeDrive.FOLDER)
        self.drive.add("Roteiro_Valido.txt", roteiros)
        self.drive.add("solto_na_raiz.txt", "root")
        with mock.patch.object(self.svc, "get_drive_client", return_value=self.drive), \
                mock.patch("googleapiclient.http.MediaIoBaseDownload", FakeDownloader):
            first = self.svc.scan_all_departments([self.rh])
            again = self.svc.scan_all_departments([self.rh])
        self.assertEqual([v.title for v in first["new_videos"]], ["Roteiro Valido"])
        self.assertEqual(again["found"], 0)

    def test_script_edited_in_drive_is_reimported_while_awaiting_review(self):
        roteiros = self.drive.add("Roteiros", "root", FakeDrive.FOLDER)
        script = self.drive.add("Boas Vindas.txt", roteiros, modified="2026-01-01T00:00:00Z")
        with mock.patch.object(self.svc, "get_drive_client", return_value=self.drive), \
                mock.patch("googleapiclient.http.MediaIoBaseDownload", FakeDownloader):
            first = self.svc.scan_all_departments([self.rh])
            video = first["new_videos"][0]
            video.set_status("AWAITING_REVIEW", "Roteiro pronto")
            self.assertEqual(self.svc.scan_all_departments([self.rh])["found"], 0)  # sem edição: nada novo

            self.drive.items[script]["modifiedTime"] = "2026-02-02T10:00:00Z"  # alguém editou no Drive
            edited = self.svc.scan_all_departments([self.rh])
        self.assertEqual([v.id for v in edited["new_videos"]], [video.id])
        video.refresh_from_db()
        self.assertEqual((video.status, video.drive_modified_at), ("PENDING", "2026-02-02T10:00:00Z"))
        self.assertEqual(TrainingVideo.objects.filter(drive_file_id=script).count(), 1)

    def test_script_edited_in_drive_is_ignored_after_approval(self):
        roteiros = self.drive.add("Roteiros", "root", FakeDrive.FOLDER)
        script = self.drive.add("Boas Vindas.txt", roteiros)
        with mock.patch.object(self.svc, "get_drive_client", return_value=self.drive), \
                mock.patch("googleapiclient.http.MediaIoBaseDownload", FakeDownloader):
            video = self.svc.scan_all_departments([self.rh])["new_videos"][0]
            video.set_status("AWAITING_VIDEO", "Roteiro aprovado", script_text="Texto aprovado.")
            self.drive.items[script]["modifiedTime"] = "2026-02-02T10:00:00Z"
            result = self.svc.scan_all_departments([self.rh])
        self.assertEqual(result["found"], 0)
        video.refresh_from_db()
        self.assertEqual((video.status, video.script_text), ("AWAITING_VIDEO", "Texto aprovado."))

    def test_video_is_uploaded_to_videos_subfolder(self):
        videos = self.drive.add("Vídeos", "root", FakeDrive.FOLDER)
        video = TrainingVideo.objects.create(
            department=self.rh, title="Check-in VIP", file_name="a.txt", status="COMPLETED",
            heygen_video_id="hg-1", video_url="https://heygen.example/v.mp4",
        )
        with mock.patch.object(self.svc, "get_drive_client", return_value=self.drive), \
                mock.patch("treinamentos.services.drive_service.httpx.stream", return_value=FakeStream()), \
                mock.patch("googleapiclient.http.MediaIoBaseUpload"):
            file_id = self.svc.upload_video(video)
        self.assertEqual(self.drive.items[file_id]["name"], "Check-in_VIP.mp4")
        self.assertEqual(self.drive.items[file_id]["parents"], [videos])


class DriveVideoSyncTests(BaseTestCase):
    """'Sincronizar Drive' publica no catálogo os MP4 que estão na subpasta Vídeos do setor."""

    def setUp(self):
        super().setUp()
        from ..services.drive_service import GoogleDriveService
        self.svc = GoogleDriveService
        self.rh.drive_folder_id = "root"
        self.rh.save()
        self.drive = FakeDrive()
        self.roteiros = self.drive.add("Roteiros", "root", FakeDrive.FOLDER)
        self.videos = self.drive.add("Vídeos", "root", FakeDrive.FOLDER)
        self.waiting = TrainingVideo.objects.create(
            department=self.rh, title="Manual de Integração", file_name="m.docx",
            status="AWAITING_VIDEO", script_text="Olá.",
        )

    def sync(self):
        with mock.patch.object(self.svc, "get_drive_client", return_value=self.drive):
            return self.svc.scan_all_departments([self.rh])

    def test_video_is_linked_to_waiting_item_by_id_in_file_properties(self):
        fid = self.drive.add("qualquer_nome.mp4", self.videos, "video/mp4", {
            "carmel_video_id": str(self.waiting.id), "heygen_video_id": "hg-5", "duration": "12.5",
        })
        result = self.sync()
        self.assertEqual(result["published"], 1)
        self.waiting.refresh_from_db()
        self.assertEqual(self.waiting.status, "COMPLETED")
        self.assertEqual((self.waiting.drive_video_id, self.waiting.heygen_video_id), (fid, "hg-5"))
        self.assertEqual(self.waiting.duration_seconds, 12.5)
        self.assertEqual(self.waiting.play_url, reverse("stream_video", args=[self.waiting.id]))

    def test_video_is_linked_by_title_when_file_has_no_properties(self):
        self.drive.add("manual de integracao.MP4", self.videos, "video/mp4")
        self.sync()
        self.waiting.refresh_from_db()
        self.assertEqual(self.waiting.status, "COMPLETED")
        self.assertEqual(TrainingVideo.objects.filter(title__icontains="integra").count(), 1)  # não duplicou

    def test_unmatched_video_is_imported_as_new_catalog_item(self):
        fid = self.drive.add("Treinamento_Novo.mp4", self.videos, "video/mp4")
        result = self.sync()
        self.assertEqual(result["published"], 1)
        item = TrainingVideo.objects.get(drive_video_id=fid)
        self.assertEqual((item.title, item.status, item.department_id), ("Treinamento Novo", "COMPLETED", self.rh.id))
        self.waiting.refresh_from_db()
        self.assertEqual(self.waiting.status, "AWAITING_VIDEO")  # o item que espera não foi tocado

    def test_second_sync_does_not_duplicate_and_ignores_non_mp4(self):
        self.drive.add("Treinamento_Novo.mp4", self.videos, "video/mp4")
        self.drive.add("rascunho.txt", self.videos, "text/plain")
        self.assertEqual(self.sync()["published"], 1)
        self.assertEqual(self.sync()["published"], 0)
        self.assertEqual(TrainingVideo.objects.filter(title="Treinamento Novo").count(), 1)

    def test_video_already_archived_by_the_system_is_skipped(self):
        fid = self.drive.add("Vídeo RH.mp4", self.videos, "video/mp4")
        self.v_rh.drive_video_id = fid  # o próprio sistema já guardou este arquivo
        self.v_rh.save()
        self.assertEqual(self.sync()["published"], 0)

    def test_sync_view_reports_published_videos(self):
        self.client.force_login(self.gestor)
        fake = {"found": 0, "new_videos": [], "published": 2, "published_videos": [], "errors": [], "drive_connected": True}
        with mock.patch("treinamentos.views.GoogleDriveService.scan_all_departments", return_value=fake):
            data = self.client.post(reverse("sync_drive")).json()
        self.assertEqual(data["published"], 2)
        self.assertIn("2 vídeo(s) carregado(s) do Drive", data["message"])
