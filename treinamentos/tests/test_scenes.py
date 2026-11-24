"""Cenas do roteiro: marcação [IMAGEM: arquivo], limpeza do texto e limite de caracteres."""

from django.test import SimpleTestCase

from ..services.document_parser import clean_script, parse_scenes, scenes_text, spoken_chars, stray_marker


class ParseScenesTests(SimpleTestCase):
    def test_without_marker_is_one_scene_identical_to_before(self):
        raw = "# Título\n\n1. Cumprimente o hóspede.\n2. Ofereça ajuda."
        scenes = parse_scenes(raw)
        self.assertEqual(scenes, [{"ordem": 1, "texto": clean_script(raw), "imagem": ""}])
        self.assertEqual(scenes_text(scenes), clean_script(raw))

    def test_marker_starts_a_scene_with_that_image(self):
        raw = "[IMAGEM: piscina.png]\nBem-vindo à piscina.\n\n[IMAGEM: bar.jpg]\nAgora o bar."
        self.assertEqual(parse_scenes(raw), [
            {"ordem": 1, "texto": "Bem-vindo à piscina.", "imagem": "piscina.png"},
            {"ordem": 2, "texto": "Agora o bar.", "imagem": "bar.jpg"},
        ])

    def test_text_before_first_marker_is_scene_one_without_image(self):
        raw = "Olá, equipe.\n[IMAGEM: recepcao.webp]\nVeja a recepção."
        scenes = parse_scenes(raw)
        self.assertEqual([(s["ordem"], s["imagem"]) for s in scenes], [(1, ""), (2, "recepcao.webp")])
        self.assertEqual(scenes[0]["texto"], "Olá, equipe.")

    def test_marker_is_never_narrated(self):
        scenes = parse_scenes("[IMAGEM: a.png]\nTexto um.\n[IMAGEM: b.png]\nTexto dois.")
        self.assertNotIn("IMAGEM", scenes_text(scenes))
        self.assertNotIn("[", scenes_text(scenes))
        self.assertEqual(scenes_text(scenes), "Texto um.\n\nTexto dois.")

    def test_marker_is_case_and_space_tolerant_and_accepts_list_or_bold(self):
        for line in ("[imagem:a.png]", "  [ Imagem :  a.png ]  ", "- [IMAGEM: a.png]", "**[IMAGEM: a.png]**"):
            scenes = parse_scenes(f"{line}\nTexto.")
            self.assertEqual(scenes[0]["imagem"], "a.png", line)
            self.assertEqual(scenes[0]["texto"], "Texto.", line)

    def test_marker_inside_a_sentence_is_ordinary_text(self):
        raw = "Veja o item [IMAGEM: a.png] no manual."
        scenes = parse_scenes(raw)
        self.assertEqual(len(scenes), 1)
        self.assertEqual(scenes[0]["imagem"], "")
        self.assertIn("[IMAGEM: a.png]", scenes[0]["texto"])

    def test_cleaning_is_kept_inside_each_scene(self):
        raw = "[IMAGEM: a.png]\n# Título\n- **Olá**, equipe\n1. Passo um\n\n\n\nFim"
        self.assertEqual(parse_scenes(raw)[0]["texto"], "Título\nOlá, equipe\nPasso um\n\nFim")

    def test_scene_without_text_is_dropped_with_a_warning(self):
        warnings = []
        scenes = parse_scenes("[IMAGEM: a.png]\n[IMAGEM: b.png]\nSó este tem texto.", warnings)
        self.assertEqual([(s["ordem"], s["imagem"]) for s in scenes], [(1, "b.png")])
        self.assertEqual(len(warnings), 1)
        self.assertIn("a.png", warnings[0])

    def test_marker_without_name_starts_a_scene_without_image(self):
        scenes = parse_scenes("Um.\n[IMAGEM: ]\nDois.")
        self.assertEqual([(s["texto"], s["imagem"]) for s in scenes], [("Um.", ""), ("Dois.", "")])

    def test_avatar_marker_brings_the_avatar_back_between_images(self):
        raw = "Abertura.\n[IMAGEM: a.png]\nUm.\n[AVATAR]\nAtenção.\n[IMAGEM: b.png]\nDois.\n[AVATAR]\nFecho."
        scenes = parse_scenes(raw)
        self.assertEqual([(s["ordem"], s["texto"], s["imagem"]) for s in scenes], [
            (1, "Abertura.", ""), (2, "Um.", "a.png"), (3, "Atenção.", ""), (4, "Dois.", "b.png"), (5, "Fecho.", ""),
        ])

    def test_avatar_marker_is_tolerant_and_never_narrated(self):
        for line in ("[AVATAR]", "[ avatar ]", "**[AVATAR]**", "- [Avatar]", "［AVATAR］"):
            scenes = parse_scenes(f"[IMAGEM: a.png]\nUm.\n{line}\nDois.")
            self.assertEqual([(s["texto"], s["imagem"]) for s in scenes], [("Um.", "a.png"), ("Dois.", "")], line)

    def test_avatar_marker_without_text_is_dropped_with_a_warning(self):
        warnings = []
        scenes = parse_scenes("[IMAGEM: a.png]\nUm.\n[AVATAR]\n[IMAGEM: b.png]\nDois.", warnings)
        self.assertEqual([s["imagem"] for s in scenes], ["a.png", "b.png"])
        self.assertEqual(len(warnings), 1)
        self.assertIn("AVATAR", warnings[0])

    def test_malformed_avatar_marker_is_a_stray_marker(self):
        self.assertTrue(stray_marker("Fale.\n[AVATAR: oi]"))
        self.assertEqual(stray_marker("Fale normalmente."), "")

    def test_empty_document_has_no_scenes(self):
        self.assertEqual(parse_scenes("   \n\n"), [])
        self.assertEqual(parse_scenes("[IMAGEM: a.png]"), [])

    def test_sentences_are_never_cut(self):
        sentence = "Esta é uma frase longa, com vírgulas; e continua até o ponto final."
        scenes = parse_scenes(f"[IMAGEM: a.png]\n{sentence}\n[IMAGEM: b.png]\n{sentence}")
        self.assertEqual([s["texto"] for s in scenes], [sentence, sentence])

    def test_limit_counts_only_spoken_text(self):
        body = "a" * 2400
        scenes = parse_scenes(f"[IMAGEM: um.png]\n{body}\n[IMAGEM: dois.png]\n{body}")
        self.assertEqual(spoken_chars(scenes), 4800)  # as marcações não entram na conta
        raw_len = len(f"[IMAGEM: um.png]\n{body}\n[IMAGEM: dois.png]\n{body}")
        self.assertGreater(raw_len, spoken_chars(scenes))
