"""Conector MCP do portal (Claude)."""

from unittest import mock

from django.test import override_settings

from ..models import TrainingVideo
from .base import BaseTestCase


@override_settings(MCP_TOKEN="chave-de-teste-123", MCP_ALLOWED_VIDEO_HOSTS=["heygen.ai", "heygen.com"])
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
