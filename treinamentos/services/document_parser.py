import re
from pathlib import Path
from typing import Tuple

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


def clean_script(text: str) -> str:
    """Prepara o texto do documento para ser narrado: remove markdown, marcadores, numeração de itens e espaços sobrando."""
    text = re.sub(r"^[ \t]*(?:#{1,6}|>|[-*•])[ \t]+", "", text, flags=re.M)  # títulos, citações, marcadores
    # numeração de itens no início da linha: "1.", "2)", "3.2", "3.2.1", "a)"
    text = re.sub(r"^[ \t]*(?:\d{1,2}(?:\.\d{1,2})*[.)]|\d{1,2}(?:\.\d{1,2})+|[a-zA-Z]\))[ \t]+", "", text, flags=re.M)
    text = re.sub(r"(\*\*|__|`)", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
