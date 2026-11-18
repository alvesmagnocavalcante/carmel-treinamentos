"""Cenas com imagem: confere se a imagem citada existe na pasta Imagens do setor e pode ser usada."""
from pathlib import Path
from typing import List, Optional

from django.conf import settings

from treinamentos.models import Department, DriveImage
from treinamentos.services.document_parser import ALLOWED_IMAGE_EXTENSIONS
from treinamentos.services.storage import name_key


def find_image(department: Department, name: str) -> Optional[DriveImage]:
    """Imagem do setor pelo nome (sem diferenciar acento nem maiúscula), ou None."""
    name = (name or "").strip()
    if not name:
        return None
    # dois arquivos com o mesmo nome: vale o alterado por último
    return DriveImage.objects.filter(department=department, name_key=name_key(name)).order_by("-modified_at", "-id").first()


def image_problem(department: Department, name: str) -> str:
    """Texto do problema com a imagem citada, ou '' se ela está pronta para uso."""
    name = (name or "").strip()
    if not name:
        return ""
    if Path(name).suffix.lower() not in ALLOWED_IMAGE_EXTENSIONS:
        return f"Imagem '{name}': use arquivo png, jpg ou webp."
    image = find_image(department, name)
    if image is None:
        return (f"Imagem '{name}' não encontrada na pasta Imagens do setor. "
                "Coloque o arquivo no Drive e clique em Sincronizar Drive.")
    if image.too_large:
        return f"Imagem '{name}' passa do limite de {settings.MAX_IMAGE_MB} MB."
    return ""


def scene_image_problems(department: Department, scenes: List[dict]) -> List[str]:
    """Problemas das imagens citadas nas cenas, sem repetir a mesma mensagem."""
    seen, problems = set(), []
    for scene in scenes:
        message = image_problem(department, scene.get("imagem", ""))
        if message and message not in seen:
            seen.add(message)
            problems.append(message)
    return problems


def check_scenes(department: Department, scenes: List[dict]) -> List[dict]:
    """As cenas com o campo `problema` preenchido quando a imagem citada não pode ser usada."""
    return [{**scene, "problema": image_problem(department, scene.get("imagem", ""))} for scene in scenes]


def usable_image_names(department: Department) -> List[str]:
    """Nomes das imagens do setor prontas para uso (para sugerir na tela de revisão)."""
    return list(
        DriveImage.objects.filter(department=department, too_large=False).order_by("name").values_list("name", flat=True)
    )
