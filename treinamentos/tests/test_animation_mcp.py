"""MCP com imagem animada: pedidos de image_to_video prontos e cena de vídeo que espera o clipe."""

import json

from django.test import SimpleTestCase, override_settings

from ..mcp_server import INSTRUCTIONS
from ..models import DriveImage, TrainingVideo
from ..services.scenes import DEFAULT_ANIMATION_PROMPT, animation_seconds
from .base import BaseTestCase

PORTAL = "https://portal.exemplo.com"


class AnimationSecondsTests(SimpleTestCase):
    def test_duration_follows_the_estimated_speech_and_is_clamped(self):
        self.assertEqual(animation_seconds("Oi."), 5)               # curto: mínimo de 5 s
        self.assertEqual(animation_seconds("a" * 140), 10)          # 140 caracteres ≈ 10 s
        self.assertEqual(animation_seconds("a" * 141), 11)          # arredonda para cima
        self.assertEqual(animation_seconds("a" * 2000), 15)         # longo: máximo de 15 s
        self.assertEqual(animation_seconds(""), 5)


@override_settings(MCP_TOKEN="chave-de-teste-123", PORTAL_BASE_URL=PORTAL)
class AnimationMcpTests(BaseTestCase):
    URL = "/mcp/chave-de-teste-123/"

    def setUp(self):
        super().setUp()
        self.rh.avatar_id, self.rh.voice_id = "av-1", "vo-2"
        self.rh.save()
        for name in ("a.png", "b.png", "c.png"):
            DriveImage.objects.create(department=self.rh, name=name, drive_file_id=f"d-{name}")

    def item(self):
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": "list_awaiting_videos", "arguments": {}}}
        resp = self.client.post(self.URL, data=json.dumps(body), content_type="application/json")
        return json.loads(resp.json()["result"]["content"][0]["text"])["videos"][0]

    def make(self, scenes):
        return TrainingVideo.objects.create(
            department=self.rh, title="Tour", file_name="t.txt", status="AWAITING_VIDEO",
            script_text="\n\n".join(s["texto"] for s in scenes), scenes=scenes,
        )

    def test_animated_scene_gets_a_ready_image_to_video_request(self):
        text = "a" * 140
        self.make([{"ordem": 1, "texto": text, "imagem": "a.png", "animar": True, "movimento": ""}])
        item = self.item()
        self.assertEqual(item["modo_heygen"], "studio")
        (animation,) = item["animacoes"]
        self.assertEqual(animation["ordem"], 1)
        args = animation["image_to_video"]
        self.assertEqual(args["image"], {"type": "url", "url": item["cenas"][0]["imagem_url"]})
        self.assertTrue(args["image"]["url"].startswith(f"{PORTAL}/imagem/"))
        self.assertEqual(args["prompt"], DEFAULT_ANIMATION_PROMPT)
        self.assertEqual((args["duration"], args["resolution"], args["promptEnhancement"]), (10, "768p", "disabled"))

    def test_custom_movement_text_is_used_as_the_prompt(self):
        self.make([{"ordem": 1, "texto": "Texto.", "imagem": "a.png", "animar": True, "movimento": "zoom lento"}])
        item = self.item()
        self.assertEqual(item["animacoes"][0]["image_to_video"]["prompt"], "zoom lento")
        self.assertEqual(item["cenas"][0]["movimento"], "zoom lento")

    def test_studio_scene_waits_for_the_clip_and_keeps_the_exact_text(self):
        exact = "Esta é a piscina.\nEla funciona das 8h às 18h."
        self.make([{"ordem": 1, "texto": exact, "imagem": "a.png", "animar": True, "movimento": ""}])
        (scene,) = self.item()["cenas_heygen"]
        self.assertEqual(scene, {
            "type": "video", "aguarda_animacao": 1, "script": exact, "voice_id": "vo-2",
            "playback": {"mode": "fit_to_scene", "mute": True},
        })
        self.assertNotIn("source", scene)  # o Claude preenche com o video_url do clipe pronto

    def test_mixed_scenes_use_the_right_type_for_each(self):
        self.make([
            {"ordem": 1, "texto": "Abertura.", "imagem": ""},
            {"ordem": 2, "texto": "A piscina.", "imagem": "a.png"},
            {"ordem": 3, "texto": "O bar.", "imagem": "b.png", "animar": True, "movimento": ""},
        ])
        item = self.item()
        self.assertEqual([s["type"] for s in item["cenas_heygen"]], ["avatar_video", "image", "video"])
        self.assertEqual([a["ordem"] for a in item["animacoes"]], [3])  # só a cena animada vira clipe

    def test_without_animation_nothing_new_appears(self):
        self.make([{"ordem": 1, "texto": "A piscina.", "imagem": "a.png"}, {"ordem": 2, "texto": "Dois.", "imagem": ""}])
        item = self.item()
        self.assertNotIn("animacoes", item)
        self.assertTrue(all("animar" not in c for c in item["cenas"]))

    @override_settings(MAX_ANIMATED_SCENES=1)
    def test_too_many_animated_scenes_block_the_item(self):
        self.make([
            {"ordem": 1, "texto": "Um.", "imagem": "a.png", "animar": True, "movimento": ""},
            {"ordem": 2, "texto": "Dois.", "imagem": "b.png", "animar": True, "movimento": ""},
        ])
        item = self.item()
        self.assertEqual((item["modo_heygen"], item["cenas_heygen"]), ("bloqueado", None))
        self.assertIn("máximo por vídeo é 1", item["motivo"])
        self.assertNotIn("animacoes", item)

    def test_animating_a_missing_image_blocks_the_item(self):
        self.make([{"ordem": 1, "texto": "Um.", "imagem": "sumiu.png", "animar": True, "movimento": ""}])
        item = self.item()
        self.assertEqual(item["modo_heygen"], "bloqueado")
        self.assertIn("sumiu.png", item["motivo"])

    def test_prompt_tells_claude_how_to_run_the_animations(self):
        for phrase in ("animacoes", "image_to_video", "aguarda_animacao", "get_model_video",
                       "NÃO troque por imagem parada", "peça todas de uma vez", "não repita um pedido"):
            self.assertIn(phrase, INSTRUCTIONS)
