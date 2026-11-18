"""Cenas com imagem: confere se a imagem citada existe na pasta Imagens do setor e pode ser usada."""
from pathlib import Path
from typing import List, Optional

from django.conf import settings
from django.core import signing
from django.urls import reverse

from treinamentos.models import Department, DriveImage
from treinamentos.services.document_parser import ALLOWED_IMAGE_EXTENSIONS
from treinamentos.services.storage import name_key, safe_filename


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


TOKEN_SALT = "carmel.scene-image"


def image_token(image: DriveImage) -> str:
    """Token assinado (com hora) que dá acesso temporário a UMA imagem, sem login."""
    return signing.dumps({"i": image.id}, salt=TOKEN_SALT, compress=True)


def image_from_token(token: str) -> Optional[DriveImage]:
    """A imagem do token, ou None se o token é falso, expirou (IMAGE_URL_TTL_MINUTES) ou a imagem não pode ser usada."""
    try:
        data = signing.loads(token, salt=TOKEN_SALT, max_age=settings.IMAGE_URL_TTL_MINUTES * 60)
        image = DriveImage.objects.get(id=int(data["i"]))
    except (signing.BadSignature, DriveImage.DoesNotExist, KeyError, TypeError, ValueError):
        return None
    return None if image.too_large else image


def portal_base_url(request) -> str:
    """Endereço público do portal para os links dados à HeyGen. Atrás de proxy (Render, Cloud Run) vale o X-Forwarded-Proto."""
    if settings.PORTAL_BASE_URL:
        return settings.PORTAL_BASE_URL
    scheme = request.headers.get("X-Forwarded-Proto", request.scheme).split(",")[0].strip() or request.scheme
    return f"{scheme}://{request.get_host()}"


def scene_image_url(image: DriveImage, request) -> str:
    """Link temporário e público (sem login, sem redirecionamento) para a HeyGen baixar a imagem da cena."""
    filename = safe_filename(image.name)
    return f"{portal_base_url(request)}{reverse('scene_image', args=[image_token(image), filename])}"


def usable_image_names(department: Department) -> List[str]:
    """Nomes das imagens do setor prontas para uso (para sugerir na tela de revisão)."""
    return list(
        DriveImage.objects.filter(department=department, too_large=False).order_by("name").values_list("name", flat=True)
    )
