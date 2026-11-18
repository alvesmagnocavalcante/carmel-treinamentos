"""Marcação de imagem: tolera espaços e caracteres que o Google Docs/Word inserem, e barra a que não foi reconhecida."""

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from ..models import TrainingVideo
from ..services.document_parser import parse_scenes, stray_marker
from ..services.pipeline import process_training_video, validate_scenes, validate_script
from .base import TMP, BaseTestCase

NB = " "  # espaço que não quebra


class MarkerToleranceTests(SimpleTestCase):
    def recognized(self, text):
        scenes = parse_scenes(text)
        return [s["imagem"] for s in scenes], scenes

    def test_special_spaces_and_invisible_characters_are_tolerated(self):
        casos = {
            "nbsp no começo": NB + "[IMAGEM: bancada.jpg]\nTexto.",
            "nbsp no fim": "[IMAGEM: bancada.jpg]" + NB + "\nTexto.",
            "nbsp depois de dois-pontos": "[IMAGEM:" + NB + "bancada.jpg]\nTexto.",
            "nbsp antes do colchete final": "[IMAGEM: bancada.jpg" + NB + "]\nTexto.",
            "espaço de largura zero": "[IMAGEM: bancada.jpg]​\nTexto.",
            "BOM no começo": "﻿[IMAGEM: bancada.jpg]\nTexto.",
            "colchetes largos": "［IMAGEM: bancada.jpg］\nTexto.",
            "dois-pontos largo": "[IMAGEM： bancada.jpg]\nTexto.",
            "tabulação": "\t[IMAGEM:\tbancada.jpg]\nTexto.",
        }
        for nome, texto in casos.items():
            imagens, scenes = self.recognized(texto)
            self.assertEqual(imagens, ["bancada.jpg"], nome)
            self.assertEqual(scenes[0]["texto"], "Texto.", nome)  # a marcação nunca é narrada

    def test_animate_modifier_tolerates_wide_pipe_and_nbsp(self):
        scenes = parse_scenes("[IMAGEM: a.png ｜" + NB + "animar:" + NB + "zoom lento]\nTexto.")
        self.assertEqual((scenes[0]["imagem"], scenes[0]["animar"], scenes[0]["movimento"]), ("a.png", True, "zoom lento"))

    def test_plain_documents_are_unchanged(self):
        scenes = parse_scenes("Olá, equipe.\n\nSegunda frase.")
        self.assertEqual(len(scenes), 1)
        self.assertEqual(scenes[0]["imagem"], "")

    def test_recognized_markers_leave_no_stray_text(self):
        warnings = []
        parse_scenes(NB + "[IMAGEM: a.png]\nUm.\n[IMAGEM: b.png | animar]\nDois.", warnings)
        self.assertEqual(warnings, [])


class StrayMarkerTests(SimpleTestCase):
    def test_detects_lines_that_look_like_a_marker_but_are_not_recognized(self):
        for texto in ("[IMAGEM piscina.png]", "[ imagem piscina.png ]", "veja [IMAGEM: piscina.png] aqui",
                      "［IMAGEM piscina.png］", "[IMAGEM: piscina.png"):
            self.assertTrue(stray_marker(texto), texto)

    def test_ordinary_text_is_not_flagged(self):
        for texto in ("Esta é a imagem da piscina.", "Tire uma imagem [com o celular].", "[nota] texto", ""):
            self.assertEqual(stray_marker(texto), "", texto)

    def test_parse_warns_about_a_marker_without_the_colon(self):
        warnings = []
        scenes = parse_scenes("Abertura.\n[IMAGEM piscina.png]\nA piscina.", warnings)
        self.assertEqual(len(scenes), 1)  # não foi reconhecida: continua no texto
        self.assertTrue(any("não foi reconhecida" in w for w in warnings))

    def test_validation_refuses_to_let_the_avatar_read_it_aloud(self):
        scenes = [{"ordem": 1, "texto": "Abertura.", "imagem": ""},
                  {"ordem": 2, "texto": "[IMAGEM piscina.png]\nA piscina.", "imagem": ""}]
        with self.assertRaises(ValueError) as ctx:
            validate_scenes(scenes)
        self.assertIn("seria lida em voz alta", str(ctx.exception))
        self.assertIn("cena 2", str(ctx.exception))
        with self.assertRaises(ValueError):
            validate_script("Texto.\n[IMAGEM piscina.png]\nMais texto.")


class StrayMarkerFlowTests(BaseTestCase):
    def job(self, content):
        dest = TMP / "temp_docs" / "marcacao.txt"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        return TrainingVideo.objects.create(department=self.rh, title="POP", file_name="marcacao.txt", source_path=str(dest))

    def test_review_flow_warns_in_the_item_message(self):
        job = self.job("Abertura.\n[IMAGEM piscina.png]\nA piscina.".encode())
        process_training_video(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, "AWAITING_REVIEW")
        self.assertIn("não foi reconhecida", job.status_message)

    @override_settings(REQUIRE_SCRIPT_REVIEW=False)
    def test_automatic_flow_fails_instead_of_narrating_the_marker(self):
        job = self.job("Abertura.\n[IMAGEM piscina.png]\nA piscina.".encode())
        process_training_video(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertIn("seria lida em voz alta", job.status_message)

    def test_review_blocks_the_approval_and_keeps_what_was_typed(self):
        job = self.job(b"Texto.")
        process_training_video(job.id)
        self.client.force_login(self.gestor)
        url = reverse("review_script", args=[job.id])
        resp = self.client.post(url, {"scene_text": ["Abertura.\n[IMAGEM piscina.png]\nA piscina."], "scene_image": [""]})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "seria lida em voz alta")
        job.refresh_from_db()
        self.assertEqual(job.status, "AWAITING_REVIEW")

    def test_marker_with_special_spaces_works_end_to_end(self):
        from ..models import DriveImage
        DriveImage.objects.create(department=self.rh, name="bancada.jpg", drive_file_id="d1")
        job = self.job(("Abertura.\n" + NB + "[IMAGEM: bancada.jpg]" + NB + "\nA bancada.").encode())
        process_training_video(job.id)
        job.refresh_from_db()
        self.assertEqual([s["imagem"] for s in job.scenes], ["", "bancada.jpg"])
        self.assertNotIn("IMAGEM", job.script_text)
