"""MCP com cenas e imagens: cenas na lista, links temporários e a rota que entrega a imagem."""

import json
import time
from unittest import mock

from django.core import signing
from django.test import override_settings

from ..mcp_server import INSTRUCTIONS
from ..models import DriveImage, TrainingVideo
from ..services.scenes import image_token
from .base import BaseTestCase
from .fakes import FakeClient, FakeUpstream

PORTAL = "https://portal.exemplo.com"


@override_settings(MCP_TOKEN="chave-de-teste-123", PORTAL_BASE_URL=PORTAL)
class McpScenesTests(BaseTestCase):
    URL = "/mcp/chave-de-teste-123/"

    def rpc(self, method, params=None, **extra):
        body = {"jsonrpc": "2.0", "id": 1, "method": method}
        if params is not None:
            body["params"] = params
        return self.client.post(self.URL, data=json.dumps(body), content_type="application/json", **extra)

    def list_items(self, **extra):
        resp = self.rpc("tools/call", {"name": "list_awaiting_videos", "arguments": {}}, **extra)
        return json.loads(resp.json()["result"]["content"][0]["text"])["videos"]

    def item(self):
        return self.list_items()[0]

    def make_waiting(self):
        return TrainingVideo.objects.create(
            department=self.rh, title="POP Vinho", file_name="p.txt", status="AWAITING_VIDEO",
            script_text="Olá, equipe. Servimos o vinho com carinho.",
        )

    def make_scenes(self, scenes):
        return TrainingVideo.objects.create(
            department=self.rh, title="Tour", file_name="t.txt", status="AWAITING_VIDEO",
            script_text="\n\n".join(s["texto"] for s in scenes), scenes=scenes,
        )

    def image(self, name="piscina.png", **kw):
        return DriveImage.objects.create(department=self.rh, name=name, drive_file_id=f"drv-{name}", **kw)

    # --- lista
    def test_item_without_images_is_one_scene_and_roteiro_is_unchanged(self):
        self.make_waiting()
        item = self.item()
        self.assertEqual(item["roteiro"], "Olá, equipe. Servimos o vinho com carinho.")
        self.assertEqual(item["cenas"], [{
            "ordem": 1, "texto": "Olá, equipe. Servimos o vinho com carinho.", "imagem": "", "imagem_url": None,
        }])

    def test_scenes_come_with_a_temporary_link_for_each_image(self):
        self.image("piscina.png")
        self.make_scenes([
            {"ordem": 1, "texto": "Abertura.", "imagem": ""},
            {"ordem": 2, "texto": "A piscina.", "imagem": "PISCINA.png"},
        ])
        item = self.item()
        self.assertEqual(item["roteiro"], "Abertura.\n\nA piscina.")  # compatível: texto completo
        first, second = item["cenas"]
        self.assertIsNone(first["imagem_url"])
        self.assertTrue(second["imagem_url"].startswith(f"{PORTAL}/imagem/"))
        self.assertTrue(second["imagem_url"].endswith("/piscina.png"))
        self.assertNotIn("imagem_erro", second)

    def test_scene_with_a_missing_or_oversized_image_has_no_link_and_says_why(self):
        self.image("enorme.png", too_large=True)
        self.make_scenes([
            {"ordem": 1, "texto": "Um.", "imagem": "sumiu.png"},
            {"ordem": 2, "texto": "Dois.", "imagem": "enorme.png"},
        ])
        sumiu, enorme = self.item()["cenas"]
        for scene, word in ((sumiu, "não encontrada"), (enorme, "limite")):
            self.assertIsNone(scene["imagem_url"])
            self.assertIn(word, scene["imagem_erro"])

    def test_base_url_follows_the_proxy_when_not_configured(self):
        self.image("piscina.png")
        self.make_scenes([{"ordem": 1, "texto": "A piscina.", "imagem": "piscina.png"}])
        with override_settings(PORTAL_BASE_URL="", ALLOWED_HOSTS=["meu-portal.onrender.com", "testserver"]):
            items = self.list_items(HTTP_X_FORWARDED_PROTO="https", HTTP_HOST="meu-portal.onrender.com")
        self.assertTrue(items[0]["cenas"][0]["imagem_url"].startswith("https://meu-portal.onrender.com/imagem/"))

    # --- rota da imagem
    def test_signed_link_serves_the_image_without_login_and_without_redirect(self):
        image = self.image("piscina.png", mime_type="image/png")
        self.make_scenes([{"ordem": 1, "texto": "A piscina.", "imagem": "piscina.png"}])
        url = self.item()["cenas"][0]["imagem_url"][len(PORTAL):]
        upstream = FakeUpstream(body=b"\x89PNG-bytes", headers={"Content-Length": "10"})
        client = FakeClient()
        with mock.patch("treinamentos.views.GoogleDriveService.open_file_stream", return_value=(client, upstream)) as opened:
            resp = self.client.get(url)  # sem login
            body = b"".join(resp.streaming_content)
        self.assertEqual(resp.status_code, 200)  # 200 direto: nada de 3xx
        self.assertEqual(resp["Content-Type"], "image/png")
        self.assertEqual(resp["Cache-Control"], "private, no-store")
        self.assertEqual(body, b"\x89PNG-bytes")
        opened.assert_called_once_with(image.drive_file_id)
        self.assertTrue(upstream.closed and client.closed)

    def test_link_expires(self):
        image = self.image("piscina.png")
        url = f"/imagem/{image_token(image)}/piscina.png"
        with mock.patch("django.core.signing.time.time", return_value=time.time() + 3 * 3600):
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_forged_or_foreign_tokens_are_rejected(self):
        image = self.image("piscina.png")
        good = image_token(image)
        foreign = signing.dumps({"i": image.id}, salt="outra.coisa")
        unknown = signing.dumps({"i": 999999}, salt="carmel.scene-image")
        for token in (good[:-3] + "xyz", foreign, "lixo", unknown):
            self.assertEqual(self.client.get(f"/imagem/{token}/a.png").status_code, 404, token)

    def test_oversized_image_is_not_served_even_with_a_valid_token(self):
        image = self.image("enorme.png", too_large=True)
        self.assertEqual(self.client.get(f"/imagem/{image_token(image)}/enorme.png").status_code, 404)

    def test_route_is_read_only_and_the_file_always_comes_from_the_token(self):
        image = self.image("piscina.png", mime_type="image/png")
        self.assertEqual(self.client.post(f"/imagem/{image_token(image)}/piscina.png").status_code, 405)
        upstream = FakeUpstream(body=b"x", headers={"Content-Length": "1"})
        with mock.patch("treinamentos.views.GoogleDriveService.open_file_stream", return_value=(FakeClient(), upstream)) as opened:
            self.client.get(f"/imagem/{image_token(image)}/qualquer.png")
            self.client.get(f"/imagem/{image_token(image)}/..%2F..%2Fetc%2Fpasswd.png")
        for call in opened.call_args_list:
            self.assertEqual(call.args, (image.drive_file_id,))

    def test_drive_failure_gives_a_clean_error(self):
        image = self.image("piscina.png", mime_type="image/png")
        with mock.patch("treinamentos.views.GoogleDriveService.open_file_stream", side_effect=RuntimeError("x")):
            self.assertEqual(self.client.get(f"/imagem/{image_token(image)}/piscina.png").status_code, 502)

    # --- prompt
    def test_instructions_tell_claude_to_stop_instead_of_improvising(self):
        for phrase in ("cenas de imagem narradas", "várias cenas", "NÃO improvise", "NÃO gere o vídeo sem as imagens",
                       "imagem_erro", "texto EXATO", "tipo image em tela cheia", "o avatar NÃO aparece",
                       "cena avatar_video"):
            self.assertIn(phrase, INSTRUCTIONS)
        # a abordagem antiga (imagem atrás do avatar) ficou para trás: o avatar cobria a imagem
        self.assertNotIn("remove_background", INSTRUCTIONS)
        initialize = self.rpc("initialize", {"protocolVersion": "2025-06-18"}).json()["result"]
        self.assertEqual(initialize["instructions"], INSTRUCTIONS)
