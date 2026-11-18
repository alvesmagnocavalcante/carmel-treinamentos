import re
from pathlib import Path
from typing import List, Optional, Tuple

from docx import Document
from pypdf import PdfReader


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


# Marcação de imagem: uma linha sozinha, ex.: [IMAGEM: piscina.png]. Tolera marcador de lista e negrito ao redor.
IMAGE_MARKER_RE = re.compile(
    r"^[ \t]*(?:[-*•>][ \t]+)?(?:\*\*|__)?\[[ \t]*IMAGEM[ \t]*:[ \t]*(?P<name>[^\]\r\n]*?)[ \t]*\](?:\*\*|__)?[ \t]*$",
    flags=re.IGNORECASE | re.MULTILINE,
)
ALLOWED_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")


def parse_scenes(raw_text: str, warnings: Optional[List[str]] = None) -> List[dict]:
    """
    Separa o roteiro em cenas [{ordem, texto, imagem}].

    Uma linha `[IMAGEM: nome.png]` abre uma cena com aquela imagem; tudo até a próxima marcação é o texto
    falado dela. O texto antes da primeira marcação é a cena 1, sem imagem. Sem nenhuma marcação, o resultado é
    uma única cena sem imagem, com o mesmo texto que clean_script() produziria (comportamento de sempre).
    A marcação nunca entra no texto narrado, e o parser só divide nas marcações: não corta o texto sozinho.
    Cenas sem texto são descartadas e, se `warnings` for dado, o motivo é anotado nele.
    """
    warn = warnings if warnings is not None else []
    matches = list(IMAGE_MARKER_RE.finditer(raw_text))

    pieces = []  # (imagem, texto bruto)
    if not matches:
        pieces.append(("", raw_text))
    else:
        pieces.append(("", raw_text[:matches[0].start()]))
        for i, match in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(raw_text)
            pieces.append((match.group("name").strip(), raw_text[match.end():end]))

    scenes = []
    for image, raw in pieces:
        text = clean_script(raw)
        if not text:
            if image:
                warn.append(f"A imagem '{image}' ficou sem texto e a cena foi ignorada.")
            continue
        scenes.append({"ordem": len(scenes) + 1, "texto": text, "imagem": image})
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
