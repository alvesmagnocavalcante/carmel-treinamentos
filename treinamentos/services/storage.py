"""Armazenamento seguro dos documentos-fonte do pipeline."""
import uuid
from pathlib import Path

from django.conf import settings
from django.utils.text import get_valid_filename


def safe_filename(name: str) -> str:
    """Remove diretórios e caracteres perigosos de um nome vindo de upload/Drive."""
    base = Path(str(name).replace("\\", "/")).name
    cleaned = get_valid_filename(base) if base else ""
    return cleaned or "documento"


def new_source_path(prefix: str, original_name: str) -> Path:
    """Caminho único dentro de TEMP_DOCS_DIR para um novo documento."""
    temp_dir = Path(settings.TEMP_DOCS_DIR)
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir / f"{prefix}_{uuid.uuid4().hex[:10]}_{safe_filename(original_name)}"


def is_allowed_extension(name: str) -> bool:
    return Path(name).suffix.lower() in settings.ALLOWED_DOC_EXTENSIONS


def title_from_filename(name: str) -> str:
    return Path(name).stem.replace("_", " ").replace("-", " ").strip().title() or "Treinamento"
