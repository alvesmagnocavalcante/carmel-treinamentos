import re
from pathlib import Path
from typing import List, Optional, Tuple

from docx import Document
from pypdf import PdfReader

from treinamentos.services.storage import name_key


class DocumentParser:
    @staticmethod
    def extract_text(file_path: Path) -> Tuple[str, str]:
        file_path = Path(file_path)
        if not file_path.is_file():
            raise FileNotFoundError(f"Arquivo não encontrado: {file_path.name}")

        ext = file_path.suffix.lower()
        if ext == ".pdf":
            text, kind = DocumentParser._parse_pdf(file_path), "pdf"
        elif ext == ".docx":
            text, kind = DocumentParser._parse_docx(file_path), "docx"
        elif ext in (".txt", ".md"):
            text, kind = DocumentParser._parse_text(file_path), "txt"
        else:
            raise ValueError(f"Formato não suportado: {ext or 'sem extensão'}. Use PDF, DOCX ou TXT.")

        if not text.strip():
            raise ValueError("Nenhum texto pôde ser extraído do documento (PDF escaneado/imagem?).")
        return text, kind

    @staticmethod
    def _parse_pdf(file_path: Path) -> str:
        reader = PdfReader(str(file_path))
        parts = [(page.extract_text() or "").strip() for page in reader.pages]
        return "\n\n".join(p for p in parts if p).strip()

    @staticmethod
    def _parse_docx(file_path: Path) -> str:
        doc = Document(str(file_path))
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                row_text = " | ".join(c.text.strip() for c in row.cells if c.text.strip())
                if row_text:
                    paragraphs.append(row_text)
        return "\n\n".join(paragraphs).strip()

    @staticmethod
    def _parse_text(file_path: Path) -> str:
        raw = file_path.read_bytes()
        for encoding in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                return raw.decode(encoding).strip()
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace").strip()


# Marcação de imagem: uma linha sozinha, ex.: [IMAGEM: piscina.png] ou [IMAGEM: piscina.png | animar: brisa leve].
# Tolera marcador de lista e negrito ao redor. Depois do "|" vem um modificador opcional (hoje só "animar").
# Espaço = qualquer espaço menos quebra de linha (`[^\S\r\n]`): inclui o espaço que não quebra (U+00A0) que o
# Google Docs e o Word colocam sem avisar.
IMAGE_MARKER_RE = re.compile(
    r"^[^\S\r\n]*(?:[-*•>][^\S\r\n]+)?(?:\*\*|__)?\[[^\S\r\n]*IMAGEM[^\S\r\n]*:[^\S\r\n]*(?P<name>[^\]\r\n|]*?)[^\S\r\n]*"
    r"(?:\|[^\S\r\n]*(?P<mod>[^\]\r\n]*?)[^\S\r\n]*)?\](?:\*\*|__)?[^\S\r\n]*$",
    flags=re.IGNORECASE | re.MULTILINE,
)
# Marcação de avatar: uma linha sozinha, [AVATAR]. Abre uma cena com o avatar falando (sem imagem), para intercalar
# avatar e imagens. Mesmas tolerâncias de espaço, lista e negrito da marcação de imagem.
AVATAR_MARKER_RE = re.compile(
    r"^[^\S\r\n]*(?:[-*•>][^\S\r\n]+)?(?:\*\*|__)?\[[^\S\r\n]*AVATAR[^\S\r\n]*\](?:\*\*|__)?[^\S\r\n]*$",
    flags=re.IGNORECASE | re.MULTILINE,
)
# Qualquer coisa que COMECE como uma marcação ("[IMAGEM", "[ imagem", "[AVATAR"): se sobrar no texto falado, é marcação com defeito.
STRAY_MARKER_RE = re.compile(r"\[[^\S\r\n]*(?:IMAGEM|AVATAR)\b", flags=re.IGNORECASE)
_INVISIBLE_RE = re.compile("[​‌‍⁠﻿]")  # espaços de largura zero e BOM
_FULLWIDTH = str.maketrans({"［": "[", "］": "]", "：": ":", "｜": "|"})  # ［ ］ ： ｜


def normalize_markup(text: str) -> str:
    """Tira caracteres invisíveis e troca colchetes, dois-pontos e barra "largos" pelos comuns, para a marcação ser achada."""
    return _INVISIBLE_RE.sub("", text).translate(_FULLWIDTH)


def stray_marker(text: str) -> str:
    """O trecho do texto falado que parece uma marcação de imagem não reconhecida, ou '' se não há."""
    text = normalize_markup(text or "")
    match = STRAY_MARKER_RE.search(text)
    if not match:
        return ""
    line_start = text.rfind("\n", 0, match.start()) + 1
    line_end = text.find("\n", match.start())
    return text[line_start: line_end if line_end != -1 else len(text)].strip()[:80]
ALLOWED_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")
MAX_MOVEMENT_CHARS = 500  # tamanho máximo do texto "como animar" de uma cena


def _parse_modifier(mod: Optional[str], image: str, warn: List[str]):
    """Modificador da marcação -> (animar, movimento). Modificador desconhecido ou sem imagem é ignorado com aviso."""
    if not mod:
        return False, ""
    head, _, rest = mod.partition(":")
    if name_key(head) != "animar":
        warn.append(f"Modificador '{mod.strip()}' desconhecido na marcação da imagem '{image}': ignorado.")
        return False, ""
    if not image:
        warn.append("Uma marcação pede para animar mas não diz o nome da imagem: a animação foi ignorada.")
        return False, ""
    return True, rest.strip()[:MAX_MOVEMENT_CHARS]


def parse_scenes(raw_text: str, warnings: Optional[List[str]] = None) -> List[dict]:
    """
    Separa o roteiro em cenas [{ordem, texto, imagem}].

    Uma linha `[IMAGEM: nome.png]` abre uma cena com aquela imagem; tudo até a próxima marcação é o texto
    falado dela. O texto antes da primeira marcação é a cena 1, sem imagem. Sem nenhuma marcação, o resultado é
    uma única cena sem imagem, com o mesmo texto que clean_script() produziria (comportamento de sempre).
    A marcação nunca entra no texto narrado, e o parser só divide nas marcações: não corta o texto sozinho.
    Cenas sem texto são descartadas e, se `warnings` for dado, o motivo é anotado nele.

    Uma linha `[AVATAR]` abre uma cena com o avatar falando (sem imagem): é como se intercala avatar e imagens.

    `[IMAGEM: nome.png | animar]` (ou `| animar: como animar`) pede uma imagem animada: a cena ganha
    `animar: True` e `movimento` (o texto de instrução, vazio = o padrão). Cenas não animadas não têm essas
    chaves, então o formato antigo não muda.
    """
    warn = warnings if warnings is not None else []
    raw_text = normalize_markup(raw_text)
    matches = sorted(list(IMAGE_MARKER_RE.finditer(raw_text)) + list(AVATAR_MARKER_RE.finditer(raw_text)),
                     key=lambda m: m.start())

    pieces = []  # (imagem, animar, movimento, texto bruto, abre_avatar)
    if not matches:
        pieces.append(("", False, "", raw_text, False))
    else:
        pieces.append(("", False, "", raw_text[:matches[0].start()], False))
        for i, match in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(raw_text)
            if match.re is AVATAR_MARKER_RE:
                pieces.append(("", False, "", raw_text[match.end():end], True))
                continue
            image = match.group("name").strip()
            animate, movement = _parse_modifier(match.group("mod"), image, warn)
            pieces.append((image, animate, movement, raw_text[match.end():end], False))

    scenes = []
    for image, animate, movement, raw, avatar in pieces:
        text = clean_script(raw)
        if not text:
            if image:
                warn.append(f"A imagem '{image}' ficou sem texto e a cena foi ignorada.")
            elif avatar:
                warn.append("Uma marcação [AVATAR] ficou sem texto e a cena foi ignorada.")
            continue
        scene = {"ordem": len(scenes) + 1, "texto": text, "imagem": image}
        if animate:
            scene.update({"animar": True, "movimento": movement})
        scenes.append(scene)
        stray = stray_marker(text)
        if stray:
            warn.append(f"A cena {scene['ordem']} tem uma linha que parece marcação de imagem mas não foi reconhecida: "
                        f"“{stray}”. Use uma linha sozinha, como [IMAGEM: arquivo.jpg] ou [AVATAR].")
    return scenes


def scenes_text(scenes: List[dict]) -> str:
    """Texto falado completo (as cenas, uma após a outra): é o que vai em script_text e no campo `roteiro`."""
    return "\n\n".join(s["texto"] for s in scenes)


def spoken_chars(scenes: List[dict]) -> int:
    """Total de caracteres narrados; o limite da HeyGen conta isto, sem as marcações."""
    return sum(len(s["texto"]) for s in scenes)


def clean_script(text: str) -> str:
    """Prepara o texto do documento para ser narrado: remove markdown, marcadores, numeração de itens e espaços sobrando."""
    text = re.sub(r"^[ \t]*(?:#{1,6}|>|[-*•])[ \t]+", "", text, flags=re.M)  # títulos, citações, marcadores
    # numeração de itens no início da linha: "1.", "2)", "3.2", "3.2.1", "a)"
    text = re.sub(r"^[ \t]*(?:\d{1,2}(?:\.\d{1,2})*[.)]|\d{1,2}(?:\.\d{1,2})+|[a-zA-Z]\))[ \t]+", "", text, flags=re.M)
    text = re.sub(r"(\*\*|__|`)", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
