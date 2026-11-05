"""Reprodução do vídeo guardado no Drive pelo portal."""

from unittest import mock

from django.urls import reverse

from .base import BaseTestCase
from .fakes import FakeClient, FakeUpstream


class VideoStreamTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.v_rh.drive_video_id = "drv-1"
        self.v_rh.save()
        self.url = reverse("stream_video", args=[self.v_rh.id])

    def stream_patch(self, upstream):
        return mock.patch(
            "treinamentos.views.GoogleDriveService.open_file_stream",
            return_value=(FakeClient(), upstream),
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
        with self.stream_patch(FakeUpstream()) as opened:
            resp = self.client.get(self.url)
            body = b"".join(resp.streaming_content)
        self.assertEqual((resp.status_code, body), (200, b"0123456789"))
        self.assertEqual(resp["Content-Type"], "video/mp4")
        self.assertEqual(resp["Accept-Ranges"], "bytes")
        opened.assert_called_once_with("drv-1", "")

    def test_range_request_returns_partial_content(self):
        self.client.force_login(self.gestor)
        upstream = FakeUpstream(206, b"2345", {"Content-Length": "4", "Content-Range": "bytes 2-5/10"})
        with self.stream_patch(upstream) as opened:
            resp = self.client.get(self.url, HTTP_RANGE="bytes=2-5")
            b"".join(resp.streaming_content)
        self.assertEqual(resp.status_code, 206)
        self.assertEqual(resp["Content-Range"], "bytes 2-5/10")
        opened.assert_called_once_with("drv-1", "bytes=2-5")
        self.assertTrue(upstream.closed)

    def test_malformed_range_is_ignored(self):
        self.client.force_login(self.gestor)
        with self.stream_patch(FakeUpstream()) as opened:
            resp = self.client.get(self.url, HTTP_RANGE="bytes=0-1,5-6")
            b"".join(resp.streaming_content)
        opened.assert_called_once_with("drv-1", "")

    def test_other_department_cannot_stream(self):
        self.client.force_login(self.colab)  # colaborador da Governança
        with self.stream_patch(FakeUpstream()) as opened:
            self.assertEqual(self.client.get(self.url).status_code, 404)
        opened.assert_not_called()

    def test_falls_back_to_heygen_link_when_drive_fails(self):
        self.client.force_login(self.gestor)
        with mock.patch("treinamentos.views.GoogleDriveService.open_file_stream", side_effect=RuntimeError("x")):
            resp = self.client.get(self.url)
        self.assertRedirects(resp, "https://x/a.mp4", fetch_redirect_response=False)

    def test_drive_error_status_falls_back_and_closes_connection(self):
        self.client.force_login(self.gestor)
        upstream = FakeUpstream(403)
        with self.stream_patch(upstream):
            resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(upstream.closed)

    def test_video_without_drive_copy_redirects_to_heygen_link(self):
        self.client.force_login(self.colab)
        resp = self.client.get(reverse("stream_video", args=[self.v_gov.id]))
        self.assertRedirects(resp, "https://x/b.mp4", fetch_redirect_response=False)
