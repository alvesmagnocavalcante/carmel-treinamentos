import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Department, SystemSetting, TrainingVideo, UserProfile, VideoProgress
from .services.pipeline import process_training_video
from .services.document_parser import clean_script
from .services.pipeline import approve_and_generate
from .services.storage import safe_filename

TMP = Path(tempfile.mkdtemp(prefix="carmel-tests-"))


def make_user(username, role, dept=None, superuser=False):
    user = (User.objects.create_superuser if superuser else User.objects.create_user)(username, password="x123456")
    user.profile.role = role
    user.profile.department = dept
    user.profile.save()
    return user


@override_settings(TEMP_DOCS_DIR=TMP / "temp_docs", MOCK_DRIVE_DIR=TMP / "mock_drive")
class BaseTestCase(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP, ignore_errors=True)

    def setUp(self):
        self.rh = Department.objects.create(code="rh", name="RH")
        self.gov = Department.objects.create(code="governanca", name="Governança")
        self.admin = make_user("admin", UserProfile.ROLE_ADMIN, superuser=True)
        self.gestor = make_user("gestor", UserProfile.ROLE_GESTOR, self.rh)
        self.colab = make_user("colab", UserProfile.ROLE_COLABORADOR, self.gov)
        self.sem_setor = make_user("semsetor", UserProfile.ROLE_COLABORADOR)
        self.v_rh = TrainingVideo.objects.create(department=self.rh, title="Vídeo RH", file_name="a.txt",
                                                 status="COMPLETED", video_url="https://x/a.mp4")
        self.v_gov = TrainingVideo.objects.create(department=self.gov, title="Vídeo Gov", file_name="b.txt",
                                                  status="COMPLETED", video_url="https://x/b.mp4")


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

    def test_colaborador_cannot_upload_or_sync(self):
        self.client.force_login(self.colab)
        self.assertEqual(self.client.get(reverse("upload_document")).status_code, 403)
        self.assertEqual(self.client.post(reverse("sync_drive")).status_code, 403)

    def test_sync_requires_post(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("sync_drive")).status_code, 405)

    @mock.patch("treinamentos.views.start_pipeline_async")
    def test_gestor_cannot_upload_to_other_department(self, start):
        self.client.force_login(self.gestor)
        f = SimpleUploadedFile("pop.txt", b"Procedimento de teste.")
        self.client.post(reverse("upload_document"), {"department_id": self.gov.id, "file": f})
        self.assertFalse(TrainingVideo.objects.filter(file_name="pop.txt").exists())
        start.assert_not_called()

    @mock.patch("treinamentos.views.start_pipeline_async")
    def test_gestor_upload_own_department(self, start):
        self.client.force_login(self.gestor)
        f = SimpleUploadedFile("../../evil name.txt", b"Procedimento de teste.")
        resp = self.client.post(reverse("upload_document"), {"department_id": self.rh.id, "file": f})
        self.assertRedirects(resp, reverse("queue"))
        video = TrainingVideo.objects.get(department=self.rh, status="PENDING")
        self.assertTrue(Path(video.source_path).is_file())
        self.assertEqual(Path(video.source_path).parent, TMP / "temp_docs")
        start.assert_called_once_with(video.id)

    @mock.patch("treinamentos.views.start_pipeline_async")
    def test_upload_rejects_unsupported_extension(self, start):
        self.client.force_login(self.admin)
        f = SimpleUploadedFile("virus.exe", b"MZ")
        self.client.post(reverse("upload_document"), {"department_id": self.rh.id, "file": f})
        self.assertFalse(TrainingVideo.objects.filter(file_name="virus.exe").exists())
        start.assert_not_called()

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


class PipelineTests(BaseTestCase):
    def make_job(self, content=b"Passo 1. Cumprimente o hospede. Passo 2. Ofereca ajuda."):
        dest = TMP / "temp_docs" / "job.txt"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        return TrainingVideo.objects.create(department=self.rh, title="POP", file_name="job.txt", source_path=str(dest))

    @override_settings(REQUIRE_SCRIPT_REVIEW=False, HEYGEN_GENERATION_MODE="api")
    @mock.patch.dict("os.environ", {"HEYGEN_MOCK_MODE": "true"})
    @mock.patch("treinamentos.services.pipeline.time.sleep")
    def test_mock_pipeline_completes(self, _sleep):
        job = self.make_job()
        process_training_video(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, "COMPLETED", job.status_message)
        self.assertTrue(job.video_url)
        self.assertIn("Cumprimente", job.script_text)

    @mock.patch("treinamentos.services.pipeline.time.sleep")
    def test_missing_file_fails_gracefully(self, _sleep):
        job = TrainingVideo.objects.create(department=self.rh, title="X", file_name="nao_existe.pdf")
        process_training_video(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")

    @override_settings(REQUIRE_SCRIPT_REVIEW=False)
    @mock.patch("treinamentos.services.pipeline.time.sleep")
    @mock.patch("treinamentos.services.heygen_service.HeyGenService.generate_video")
    def test_script_over_heygen_limit_fails_without_calling_heygen(self, gen, _sleep):
        job = self.make_job(content=("Frase de teste. " * 400).encode())
        process_training_video(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertIn("limite da HeyGen", job.status_message)
        gen.assert_not_called()

    @mock.patch.dict("os.environ", {"HEYGEN_MOCK_MODE": "false", "HEYGEN_API_KEY": "k",
                                    "DEFAULT_AVATAR_ID": "av", "DEFAULT_VOICE_ID": "vo"})
    @override_settings(REQUIRE_SCRIPT_REVIEW=False, HEYGEN_GENERATION_MODE="api")
    @mock.patch("treinamentos.services.pipeline.time.sleep")
    @mock.patch("treinamentos.services.heygen_service.HeyGenService.check_video_status")
    @mock.patch("treinamentos.services.heygen_service.HeyGenService.generate_video")
    def test_real_heygen_is_polled_until_completed(self, gen, check, _sleep):
        gen.return_value = {"video_id": "real-123", "mock": False}
        check.side_effect = [
            {"status": "processing"},
            {"status": "completed", "video_url": "https://cdn/v.mp4", "thumbnail_url": "", "duration": 61.0},
        ]
        job = self.make_job()
        process_training_video(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, "COMPLETED")
        self.assertEqual(job.video_url, "https://cdn/v.mp4")
        self.assertEqual(check.call_count, 2)

    def test_empty_db_setting_falls_back_to_env(self):
        SystemSetting.objects.create(key="heygen_api_key", value="")
        self.assertEqual(SystemSetting.get_val("heygen_api_key", "from-env"), "from-env")

    def test_drive_scan_picks_up_local_files_once(self):
        from .services.drive_service import GoogleDriveService
        folder = TMP / "mock_drive" / "rh" / "Roteiros"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "Manual.txt").write_text("Conteudo do manual.", encoding="utf-8")
        (folder / "foto.png").write_bytes(b"x")
        with mock.patch.object(GoogleDriveService, "get_drive_client", return_value=None):
            first = GoogleDriveService.scan_all_departments([self.rh])
            second = GoogleDriveService.scan_all_departments([self.rh])
        self.assertEqual(first["found"], 1)
        self.assertEqual(second["found"], 0)


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

    @mock.patch("treinamentos.services.heygen_service.HeyGenService.generate_video")
    def test_pipeline_stops_for_review_without_calling_heygen(self, gen):
        dest = TMP / "temp_docs" / "rev.txt"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"1. Cumprimente o hospede.")
        job = TrainingVideo.objects.create(department=self.rh, title="POP", file_name="rev.txt", source_path=str(dest))
        process_training_video(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, "AWAITING_REVIEW")
        self.assertEqual(job.script_text, "Cumprimente o hospede.")
        gen.assert_not_called()

    @override_settings(HEYGEN_GENERATION_MODE="api")
    @mock.patch("treinamentos.views.start_pipeline_async")
    def test_gestor_approves_edited_script(self, start):
        job = self.make_waiting()
        self.client.force_login(self.gestor)
        self.assertEqual(self.client.get(reverse("review_script", args=[job.id])).status_code, 200)
        resp = self.client.post(reverse("review_script", args=[job.id]), {"script": "Texto **corrigido**."})
        self.assertRedirects(resp, reverse("queue"))
        job.refresh_from_db()
        self.assertEqual(job.script_text, "Texto corrigido.")
        self.assertEqual(job.status, "PENDING")
        start.assert_called_once_with(job.id, approve_and_generate)

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

    @mock.patch("treinamentos.services.pipeline.time.sleep")
    @mock.patch.dict("os.environ", {"HEYGEN_MOCK_MODE": "true"})
    def test_approved_script_generates_video(self, _sleep):
        job = self.make_waiting()
        approve_and_generate(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, "COMPLETED", job.status_message)


class _Exec:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


class FakeDrive:
    """Google Drive em memória: {id: {name, mimeType, parents}}."""
    FOLDER = "application/vnd.google-apps.folder"

    def __init__(self):
        self.items, self.n = {}, 0

    def add(self, name, parent, mime="text/plain", props=None):
        self.n += 1
        item_id = f"id{self.n}"
        self.items[item_id] = {"name": name, "mimeType": mime, "parents": [parent], "appProperties": props or {}}
        return item_id

    def files(self):
        return self

    def list(self, q, **kw):
        parent = q.split("'")[1]
        want_folders = "mimeType = '" in q and "!=" not in q
        found = [
            {**v, "id": k, "modifiedTime": "2026-01-01T00:00:00Z"} for k, v in self.items.items()
            if parent in v["parents"] and (v["mimeType"] == self.FOLDER) == want_folders
        ]
        return _Exec({"files": found})

    def create(self, body, **kw):
        return _Exec({"id": self.add(
            body["name"], body["parents"][0], body.get("mimeType", "video/mp4"), body.get("appProperties"),
        )})

    def get_media(self, **kw):
        return object()


class _FakeDownloader:
    def __init__(self, fh, request):
        self.fh = fh

    def next_chunk(self):
        self.fh.write(b"Ola equipe.")
        return None, True


class _FakeStream:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        pass

    def iter_bytes(self, n):
        yield b"fake-mp4-bytes"


class DriveFolderStructureTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        from .services.drive_service import GoogleDriveService
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
        with mock.patch.object(self.svc, "get_drive_client", return_value=self.drive),                 mock.patch("googleapiclient.http.MediaIoBaseDownload", _FakeDownloader):
            first = self.svc.scan_all_departments([self.rh])
            again = self.svc.scan_all_departments([self.rh])
        self.assertEqual([v.title for v in first["new_videos"]], ["Roteiro Valido"])
        self.assertEqual(again["found"], 0)

    def test_video_is_uploaded_to_videos_subfolder(self):
        videos = self.drive.add("Vídeos", "root", FakeDrive.FOLDER)
        video = TrainingVideo.objects.create(
            department=self.rh, title="Check-in VIP", file_name="a.txt", status="COMPLETED",
            heygen_video_id="hg-1", video_url="https://heygen.example/v.mp4",
        )
        with mock.patch.object(self.svc, "get_drive_client", return_value=self.drive),                 mock.patch("treinamentos.services.drive_service.httpx.stream", return_value=_FakeStream()),                 mock.patch("googleapiclient.http.MediaIoBaseUpload"):
            file_id = self.svc.upload_video(video)
        self.assertEqual(self.drive.items[file_id]["name"], "Check-in_VIP.mp4")
        self.assertEqual(self.drive.items[file_id]["parents"], [videos])

    @mock.patch("treinamentos.services.drive_service.GoogleDriveService.upload_video", return_value="drv-9")
    def test_completed_video_is_archived_to_drive(self, upload):
        from .services.pipeline import archive_video_to_drive
        video = TrainingVideo.objects.create(
            department=self.rh, title="X", file_name="a.txt", status="COMPLETED",
            heygen_video_id="hg-1", video_url="https://heygen.example/v.mp4",
        )
        archive_video_to_drive(video)
        video.refresh_from_db()
        self.assertEqual(video.drive_video_id, "drv-9")
        self.assertEqual(video.status, "COMPLETED")

    @mock.patch("treinamentos.services.drive_service.GoogleDriveService.upload_video", side_effect=RuntimeError("sem permissão"))
    def test_drive_failure_keeps_video_available(self, upload):
        from .services.pipeline import archive_video_to_drive
        video = TrainingVideo.objects.create(
            department=self.rh, title="X", file_name="a.txt", status="COMPLETED",
            heygen_video_id="hg-1", video_url="https://heygen.example/v.mp4",
        )
        archive_video_to_drive(video)
        video.refresh_from_db()
        self.assertEqual(video.status, "COMPLETED")
        self.assertEqual(video.drive_video_id, "")
        self.assertIn("não foi salvo no Drive", video.status_message)

    @mock.patch("treinamentos.services.drive_service.GoogleDriveService.upload_video")
    def test_mock_videos_are_not_uploaded(self, upload):
        from .services.pipeline import archive_video_to_drive
        video = TrainingVideo.objects.create(
            department=self.rh, title="X", file_name="a.txt", status="COMPLETED",
            heygen_video_id="mock-abc", video_url="https://x/bunny.mp4",
        )
        archive_video_to_drive(video)
        upload.assert_not_called()


class _FakeUpstream:
    """Resposta do Drive simulada (mesma interface usada do httpx)."""
    def __init__(self, status=200, body=b"0123456789", headers=None):
        self.status_code, self.body = status, body
        self.headers = headers or {"Content-Length": str(len(body))}
        self.closed = False

    def iter_bytes(self, n):
        yield self.body

    def close(self):
        self.closed = True


class _FakeClient:
    closed = False

    def close(self):
        self.closed = True


class VideoStreamTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.v_rh.drive_video_id = "drv-1"
        self.v_rh.save()
        self.url = reverse("stream_video", args=[self.v_rh.id])

    def stream_patch(self, upstream):
        return mock.patch(
            "treinamentos.views.GoogleDriveService.open_file_stream",
            return_value=(_FakeClient(), upstream),
        )

    def test_play_url_uses_portal_stream_when_saved_in_drive(self):
        self.assertEqual(self.v_rh.play_url, self.url)
        self.assertEqual(self.v_gov.play_url, "https://x/b.mp4")  # sem cópia no Drive: link da HeyGen

    def test_catalog_plays_drive_copy(self):
        self.client.force_login(self.gestor)
        html = self.client.get(reverse("home")).content.decode()
        self.assertIn(f'data-video-url="{self.url}"', html)

    def test_requires_login(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_streams_full_file_from_drive(self):
        self.client.force_login(self.gestor)
        with self.stream_patch(_FakeUpstream()) as opened:
            resp = self.client.get(self.url)
            body = b"".join(resp.streaming_content)
        self.assertEqual((resp.status_code, body), (200, b"0123456789"))
        self.assertEqual(resp["Content-Type"], "video/mp4")
        self.assertEqual(resp["Accept-Ranges"], "bytes")
        opened.assert_called_once_with("drv-1", "")

    def test_range_request_returns_partial_content(self):
        self.client.force_login(self.gestor)
        upstream = _FakeUpstream(206, b"2345", {"Content-Length": "4", "Content-Range": "bytes 2-5/10"})
        with self.stream_patch(upstream) as opened:
            resp = self.client.get(self.url, HTTP_RANGE="bytes=2-5")
            b"".join(resp.streaming_content)
        self.assertEqual(resp.status_code, 206)
        self.assertEqual(resp["Content-Range"], "bytes 2-5/10")
        opened.assert_called_once_with("drv-1", "bytes=2-5")
        self.assertTrue(upstream.closed)

    def test_malformed_range_is_ignored(self):
        self.client.force_login(self.gestor)
        with self.stream_patch(_FakeUpstream()) as opened:
            resp = self.client.get(self.url, HTTP_RANGE="bytes=0-1,5-6")
            b"".join(resp.streaming_content)
        opened.assert_called_once_with("drv-1", "")

    def test_other_department_cannot_stream(self):
        self.client.force_login(self.colab)  # colaborador da Governança
        with self.stream_patch(_FakeUpstream()) as opened:
            self.assertEqual(self.client.get(self.url).status_code, 404)
        opened.assert_not_called()

    def test_falls_back_to_heygen_link_when_drive_fails(self):
        self.client.force_login(self.gestor)
        with mock.patch("treinamentos.views.GoogleDriveService.open_file_stream", side_effect=RuntimeError("x")):
            resp = self.client.get(self.url)
        self.assertRedirects(resp, "https://x/a.mp4", fetch_redirect_response=False)

    def test_drive_error_status_falls_back_and_closes_connection(self):
        self.client.force_login(self.gestor)
        upstream = _FakeUpstream(403)
        with self.stream_patch(upstream):
            resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(upstream.closed)

    def test_video_without_drive_copy_redirects_to_heygen_link(self):
        self.client.force_login(self.colab)
        resp = self.client.get(reverse("stream_video", args=[self.v_gov.id]))
        self.assertRedirects(resp, "https://x/b.mp4", fetch_redirect_response=False)


@override_settings(HEYGEN_GENERATION_MODE="manual")
class AwaitingVideoTests(BaseTestCase):
    def make_waiting(self, dept=None, status="AWAITING_VIDEO"):
        return TrainingVideo.objects.create(
            department=dept or self.rh, title="POP Vinho", file_name="p.txt",
            status=status, script_text="Olá, equipe. Servimos o vinho com carinho.",
        )

    @override_settings(REQUIRE_SCRIPT_REVIEW=False)
    @mock.patch("treinamentos.services.heygen_service.HeyGenService.generate_video")
    def test_pipeline_waits_for_video_in_manual_mode(self, gen):
        dest = TMP / "temp_docs" / "man.txt"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"Cumprimente o hospede.")
        job = TrainingVideo.objects.create(department=self.rh, title="POP", file_name="man.txt", source_path=str(dest))
        process_training_video(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, "AWAITING_VIDEO")
        self.assertIn("Aguardando a geração do vídeo", job.status_message)
        gen.assert_not_called()

    @mock.patch("treinamentos.views.start_pipeline_async")
    def test_approval_in_manual_mode_waits_instead_of_calling_heygen(self, start):
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

    @mock.patch("treinamentos.services.drive_service.GoogleDriveService.upload_video", return_value="drv-1")
    def test_complete_video_publishes_and_archives(self, upload):
        from .services.pipeline import complete_video
        job = self.make_waiting()
        complete_video(job, video_url="https://x/v.mp4", heygen_video_id="hg-9", thumbnail_url="https://x/t.jpg", duration=5.8)
        job.refresh_from_db()
        self.assertEqual((job.status, job.heygen_video_id, job.drive_video_id), ("COMPLETED", "hg-9", "drv-1"))
        self.assertEqual(job.duration_formatted, "0:05")
        self.assertIsNotNone(job.completed_at)

    def test_register_video_command_two_steps(self):
        from io import StringIO
        from django.core.management import call_command
        from django.core.management.base import CommandError
        from .services.drive_service import GoogleDriveService
        job = self.make_waiting()
        out = StringIO()
        call_command("register_video", job.id, "--heygen-id", "hg-1", stdout=out)
        job.refresh_from_db()
        self.assertEqual((job.status, job.heygen_video_id), ("GENERATING_HEYGEN", "hg-1"))
        with mock.patch.object(GoogleDriveService, "get_drive_client", return_value=None):
            call_command("register_video", job.id, "--heygen-id", "hg-1", "--url", "https://x/v.mp4",
                         "--duration", "5.8", stdout=out)
        job.refresh_from_db()
        self.assertEqual(job.status, "COMPLETED")
        self.assertEqual(job.video_url, "https://x/v.mp4")
        with self.assertRaises(CommandError):
            call_command("register_video", job.id, "--heygen-id", "hg-1", stdout=out)

    def test_list_awaiting_videos_command_shows_script_and_params(self):
        from io import StringIO
        from django.core.management import call_command
        job = self.make_waiting()
        out = StringIO()
        with mock.patch.dict("os.environ", {"DEFAULT_AVATAR_ID": "av-x", "DEFAULT_VOICE_ID": "vo-y"}):
            call_command("list_awaiting_videos", stdout=out)
        text = out.getvalue()
        self.assertIn(f"[{job.id}]", text)
        self.assertIn("av-x", text)
        self.assertIn("Servimos o vinho com carinho", text)


class DriveVideoSyncTests(BaseTestCase):
    """'Sincronizar Drive' publica no catálogo os MP4 que estão na subpasta Vídeos do setor."""

    def setUp(self):
        super().setUp()
        from .services.drive_service import GoogleDriveService
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

    @mock.patch("treinamentos.services.drive_service.GoogleDriveService.upload_video", return_value="drv-3")
    def test_upload_generated_video_saves_to_drive_but_leaves_publishing_to_sync(self, upload):
        from io import StringIO
        from django.core.management import call_command
        call_command("upload_generated_video", self.waiting.id, "--url", "https://x/v.mp4",
                     "--heygen-id", "hg-7", "--duration", "9.5", stdout=StringIO())
        self.waiting.refresh_from_db()
        self.assertEqual(self.waiting.status, "AWAITING_VIDEO")
        self.assertEqual((self.waiting.drive_video_id, self.waiting.heygen_video_id), ("", "hg-7"))
        self.assertEqual(self.waiting.duration_seconds, 9.5)
        self.assertIn("Sincronizar Drive", self.waiting.status_message)

    def test_upload_generated_video_fails_clearly_without_drive_folder(self):
        from io import StringIO
        from django.core.management import call_command
        from django.core.management.base import CommandError
        self.rh.drive_folder_id = ""
        self.rh.save()
        with self.assertRaises(CommandError):
            call_command("upload_generated_video", self.waiting.id, "--url", "https://x/v.mp4", stdout=StringIO())
        self.waiting.refresh_from_db()
        self.assertEqual(self.waiting.status, "AWAITING_VIDEO")



@override_settings(MCP_TOKEN="chave-de-teste-123", MCP_ALLOWED_VIDEO_HOSTS=["heygen.ai", "heygen.com"],
                   HEYGEN_GENERATION_MODE="manual")
class McpConnectorTests(BaseTestCase):
    URL = "/mcp/chave-de-teste-123/"

    def rpc(self, method, params=None, msg_id=1, url=None, **extra):
        import json
        body = {"jsonrpc": "2.0", "method": method}
        if msg_id is not None:
            body["id"] = msg_id
        if params is not None:
            body["params"] = params
        return self.client.post(url or self.URL, data=json.dumps(body), content_type="application/json", **extra)

    def call(self, name, arguments=None):
        import json
        resp = self.rpc("tools/call", {"name": name, "arguments": arguments or {}})
        result = resp.json()["result"]
        return result["isError"], json.loads(result["content"][0]["text"])

    def make_waiting(self, status="AWAITING_VIDEO"):
        return TrainingVideo.objects.create(
            department=self.rh, title="POP Vinho", file_name="p.txt", status=status,
            script_text="Olá, equipe. Servimos o vinho com carinho.",
        )

    # --- acesso
    @override_settings(MCP_TOKEN="")
    def test_connector_is_off_without_token(self):
        self.assertEqual(self.rpc("ping", url="/mcp/qualquer/").status_code, 404)
        self.assertEqual(self.rpc("ping", url="/mcp/").status_code, 404)

    def test_wrong_path_token_is_404_and_bearer_is_401(self):
        self.assertEqual(self.rpc("ping", url="/mcp/errada/").status_code, 404)
        self.assertEqual(self.rpc("ping", url="/mcp/").status_code, 401)
        self.assertEqual(self.rpc("ping", url="/mcp/", HTTP_AUTHORIZATION="Bearer errada").status_code, 401)

    def test_bearer_header_is_accepted(self):
        resp = self.rpc("ping", url="/mcp/", HTTP_AUTHORIZATION="Bearer chave-de-teste-123")
        self.assertEqual((resp.status_code, resp.json()["result"]), (200, {}))

    def test_only_post_is_allowed(self):
        self.assertEqual(self.client.get(self.URL).status_code, 405)

    # --- protocolo
    def test_initialize_negotiates_version_and_declares_tools(self):
        result = self.rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {}}).json()["result"]
        self.assertEqual(result["protocolVersion"], "2025-03-26")
        self.assertIn("tools", result["capabilities"])
        self.assertEqual(result["serverInfo"]["name"], "carmel-treinamentos")
        unknown = self.rpc("initialize", {"protocolVersion": "1999-01-01"}).json()["result"]
        self.assertEqual(unknown["protocolVersion"], "2025-06-18")

    def test_notification_gets_202_and_unknown_method_errors(self):
        self.assertEqual(self.rpc("notifications/initialized", msg_id=None).status_code, 202)
        self.assertEqual(self.rpc("nao/existe").json()["error"]["code"], -32601)

    def test_invalid_json_and_batch(self):
        import json
        bad = self.client.post(self.URL, data="{nao e json", content_type="application/json")
        self.assertEqual((bad.status_code, bad.json()["error"]["code"]), (400, -32700))
        batch = self.client.post(self.URL, data=json.dumps([
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
        ]), content_type="application/json")
        self.assertEqual(len(batch.json()), 1)

    def test_tools_list_has_schemas(self):
        tools = {t["name"]: t for t in self.rpc("tools/list").json()["result"]["tools"]}
        self.assertEqual(set(tools), {"list_awaiting_videos", "mark_video_rendering", "save_generated_video", "get_video_status"})
        self.assertEqual(tools["save_generated_video"]["inputSchema"]["required"], ["video_id", "video_url"])

    def test_unknown_tool_is_a_protocol_error(self):
        resp = self.rpc("tools/call", {"name": "apagar_tudo", "arguments": {}}).json()
        self.assertEqual(resp["error"]["code"], -32602)

    # --- ferramentas
    def test_list_awaiting_videos_returns_exact_script_and_params(self):
        job = self.make_waiting()
        self.make_waiting(status="COMPLETED")  # não deve aparecer
        with mock.patch.dict("os.environ", {"DEFAULT_AVATAR_ID": "av-1", "DEFAULT_VOICE_ID": "vo-2"}):
            err, data = self.call("list_awaiting_videos")
        self.assertFalse(err)
        self.assertEqual(data["total"], 1)
        item = data["videos"][0]
        self.assertEqual((item["video_id"], item["avatar_id"], item["voice_id"]), (job.id, "av-1", "vo-2"))
        self.assertEqual(item["roteiro"], "Olá, equipe. Servimos o vinho com carinho.")

    def test_list_can_filter_by_department(self):
        self.make_waiting()
        self.assertEqual(self.call("list_awaiting_videos", {"setor": "governanca"})[1]["total"], 0)

    def test_mark_video_rendering(self):
        job = self.make_waiting()
        err, data = self.call("mark_video_rendering", {"video_id": job.id, "heygen_video_id": "hg-1"})
        self.assertFalse(err)
        job.refresh_from_db()
        self.assertEqual((job.status, job.heygen_video_id), ("GENERATING_HEYGEN", "hg-1"))

    def test_mark_rejects_completed_item_and_missing_id(self):
        done = self.make_waiting(status="COMPLETED")
        self.assertTrue(self.call("mark_video_rendering", {"video_id": done.id, "heygen_video_id": "x"})[0])
        self.assertTrue(self.call("mark_video_rendering", {"video_id": 999999, "heygen_video_id": "x"})[0])
        self.assertTrue(self.call("mark_video_rendering", {"video_id": done.id})[0])

    @mock.patch("treinamentos.services.drive_service.GoogleDriveService.upload_video", return_value="drv-5")
    def test_save_generated_video_publishes_by_default(self, upload):
        job = self.make_waiting()
        err, data = self.call("save_generated_video", {
            "video_id": job.id, "video_url": "https://files2.heygen.ai/x/v.mp4",
            "heygen_video_id": "hg-9", "duration_seconds": 3.2,
        })
        self.assertFalse(err, data)
        self.assertTrue(data["publicado"])
        job.refresh_from_db()
        self.assertEqual((job.status, job.drive_video_id, job.heygen_video_id), ("COMPLETED", "drv-5", "hg-9"))
        self.assertEqual(job.duration_seconds, 3.2)

    @mock.patch("treinamentos.services.drive_service.GoogleDriveService.upload_video", return_value="drv-6")
    def test_save_generated_video_without_publish_waits_for_sync(self, upload):
        job = self.make_waiting()
        err, data = self.call("save_generated_video", {
            "video_id": job.id, "video_url": "https://files2.heygen.ai/x/v.mp4", "publish": False,
        })
        self.assertFalse(err, data)
        self.assertFalse(data["publicado"])
        job.refresh_from_db()
        self.assertEqual((job.status, job.drive_video_id), ("AWAITING_VIDEO", ""))

    @mock.patch("treinamentos.services.drive_service.GoogleDriveService.upload_video")
    def test_save_rejects_links_outside_heygen(self, upload):
        job = self.make_waiting()
        for bad in ("https://evil.com/v.mp4", "http://files2.heygen.ai/v.mp4", "https://heygen.ai.evil.com/v.mp4",
                    "file:///etc/passwd", "http://169.254.169.254/latest/meta-data/", ""):
            err, data = self.call("save_generated_video", {"video_id": job.id, "video_url": bad})
            self.assertTrue(err, bad)
        upload.assert_not_called()

    @mock.patch("treinamentos.services.drive_service.GoogleDriveService.upload_video", return_value=None)
    def test_save_reports_missing_drive_setup_and_keeps_item_waiting(self, upload):
        job = self.make_waiting()
        err, data = self.call("save_generated_video", {"video_id": job.id, "video_url": "https://files2.heygen.ai/v.mp4"})
        self.assertTrue(err)
        self.assertIn("Drive", data["erro"])
        job.refresh_from_db()
        self.assertEqual(job.status, "AWAITING_VIDEO")

    @mock.patch("treinamentos.services.drive_service.GoogleDriveService.upload_video", side_effect=RuntimeError("quota"))
    def test_save_reports_drive_failure(self, upload):
        job = self.make_waiting()
        err, data = self.call("save_generated_video", {"video_id": job.id, "video_url": "https://files2.heygen.ai/v.mp4"})
        self.assertTrue(err)
        self.assertIn("quota", data["erro"])

    def test_save_cannot_overwrite_a_completed_item(self):
        done = self.make_waiting(status="COMPLETED")
        err, data = self.call("save_generated_video", {"video_id": done.id, "video_url": "https://files2.heygen.ai/v.mp4"})
        self.assertTrue(err)

    def test_get_video_status(self):
        job = self.make_waiting()
        err, data = self.call("get_video_status", {"video_id": job.id})
        self.assertEqual((err, data["status"], data["salvo_no_drive"]), (False, "Aguardando Vídeo", False))
