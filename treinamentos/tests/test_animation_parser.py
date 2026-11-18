"""Imagem animada: modificador `| animar` na marcação e limite de cenas animadas."""

from django.test import SimpleTestCase, override_settings

from ..services.document_parser import MAX_MOVEMENT_CHARS, parse_scenes, scenes_text
from ..services.pipeline import validate_scenes


class AnimateMarkerTests(SimpleTestCase):
    def test_animar_marks_the_scene_with_the_default_movement(self):
        scenes = parse_scenes("[IMAGEM: piscina.png | animar]\nA piscina.")
        self.assertEqual(scenes, [{"ordem": 1, "texto": "A piscina.", "imagem": "piscina.png",
                                   "animar": True, "movimento": ""}])

    def test_animar_with_a_custom_movement(self):
        scenes = parse_scenes("[IMAGEM: piscina.png | animar: brisa leve nas palmeiras, água calma]\nA piscina.")
        self.assertEqual(scenes[0]["movimento"], "brisa leve nas palmeiras, água calma")
        self.assertTrue(scenes[0]["animar"])

    def test_modifier_is_case_accent_and_space_tolerant(self):
        for line in ("[IMAGEM: a.png|ANIMAR]", "[imagem: a.png  |  Animar ]", "- [IMAGEM: a.png | animar:]",
                     "**[IMAGEM: a.png | animar]**"):
            scenes = parse_scenes(f"{line}\nTexto.")
            self.assertTrue(scenes[0]["animar"], line)
            self.assertEqual(scenes[0]["imagem"], "a.png", line)

    def test_marker_is_never_narrated_even_with_modifier(self):
        scenes = parse_scenes("Abertura.\n[IMAGEM: a.png | animar: zoom lento]\nFim.")
        self.assertEqual(scenes_text(scenes), "Abertura.\n\nFim.")

    def test_scenes_without_animation_keep_the_old_format(self):
        scenes = parse_scenes("[IMAGEM: a.png]\nUm.\n[IMAGEM: b.png | animar]\nDois.")
        self.assertEqual(scenes[0], {"ordem": 1, "texto": "Um.", "imagem": "a.png"})  # sem chaves novas
        self.assertTrue(scenes[1]["animar"])

    def test_unknown_modifier_is_ignored_with_a_warning(self):
        warnings = []
        scenes = parse_scenes("[IMAGEM: a.png | girar]\nTexto.", warnings)
        self.assertEqual(scenes, [{"ordem": 1, "texto": "Texto.", "imagem": "a.png"}])
        self.assertEqual(len(warnings), 1)
        self.assertIn("girar", warnings[0])

    def test_animar_without_an_image_name_is_ignored_with_a_warning(self):
        warnings = []
        scenes = parse_scenes("[IMAGEM: | animar]\nTexto.", warnings)
        self.assertEqual(scenes, [{"ordem": 1, "texto": "Texto.", "imagem": ""}])
        self.assertTrue(warnings)

    def test_pipe_does_not_leak_into_the_image_name(self):
        scenes = parse_scenes("[IMAGEM: piscina 1.jpg | animar]\nTexto.")
        self.assertEqual(scenes[0]["imagem"], "piscina 1.jpg")

    def test_movement_is_capped(self):
        scenes = parse_scenes("[IMAGEM: a.png | animar: " + "x" * 900 + "]\nTexto.")
        self.assertEqual(len(scenes[0]["movimento"]), MAX_MOVEMENT_CHARS)


class AnimatedSceneLimitTests(SimpleTestCase):
    def scenes(self, animated, total=None):
        total = total or animated
        return [{"ordem": i + 1, "texto": f"Cena {i + 1}.", "imagem": "a.png",
                 **({"animar": True, "movimento": ""} if i < animated else {})} for i in range(total)]

    @override_settings(MAX_ANIMATED_SCENES=2)
    def test_up_to_the_limit_is_fine(self):
        validate_scenes(self.scenes(2, total=3))

    @override_settings(MAX_ANIMATED_SCENES=2)
    def test_over_the_limit_is_refused_with_a_clear_message(self):
        with self.assertRaises(ValueError) as ctx:
            validate_scenes(self.scenes(3))
        self.assertIn("máximo por vídeo é 2", str(ctx.exception))

    def test_animation_needs_an_image(self):
        scenes = [{"ordem": 1, "texto": "Texto.", "imagem": "", "animar": True, "movimento": ""}]
        with self.assertRaises(ValueError) as ctx:
            validate_scenes(scenes)
        self.assertIn("não tem imagem", str(ctx.exception))
