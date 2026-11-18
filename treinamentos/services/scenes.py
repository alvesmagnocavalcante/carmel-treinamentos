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


MIN_LANDSCAPE_RATIO = 1.4  # abaixo disso (4:3, quadrada, em pé) o corte no 16:9 já come uma parte relevante da foto


def image_notice(department: Department, name: str) -> str:
    """Aviso (não bloqueia) sobre a imagem citada: foto em pé ou quase quadrada é cortada no vídeo 16:9."""
    image = find_image(department, name)
    if image is None or not image.width or not image.height:
        return ""
    if image.width / image.height < MIN_LANDSCAPE_RATIO:
        return (f"A imagem '{image.name}' é em pé ou quase quadrada ({image.width}×{image.height}): "
                "no vídeo 16:9 ela será cortada. Prefira fotos na horizontal.")
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
    """As cenas com `problema` (a imagem citada não pode ser usada) e `aviso` (pode, mas com ressalva) preenchidos."""
    return [
        {**scene,
         "problema": image_problem(department, scene.get("imagem", "")),
         "aviso": image_notice(department, scene.get("imagem", ""))}
        for scene in scenes
    ]


# Animar com IA é arriscado: quanto mais livre a instrução e mais longo o clipe, mais a IA inventa. Por isso o padrão
# é SÓ movimento de câmera (a cena em si fica parada), em inglês (a IA obedece melhor) e com proibições explícitas.
DEFAULT_ANIMATION_PROMPT = (
    "Very slow, subtle camera push-in. Keep the scene exactly as in the photo: do not animate, move, add, remove or "
    "change any object, food, hands, people, animals, text or logos. No new elements. Realistic, photographic, stable."
)
# Acrescentado a qualquer texto de movimento escrito pela equipe, para ele não abrir a porta para invenções.
ANIMATION_GUARD = (
    "Keep everything else exactly as in the photo: do not add, remove, move or deform any object, food, hands, "
    "people, animals, text or logos."
)
MIN_CLIP_SECONDS, MAX_CLIP_SECONDS = 5, 15  # 5 s é o mínimo da HeyGen; acima de 15 s ela exige o aprimoramento de texto


def animation_prompt(movement: str) -> str:
    """Texto de instrução enviado à IA: o padrão, ou o da equipe seguido da trava contra invenções."""
    movement = (movement or "").strip()
    if not movement:
        return DEFAULT_ANIMATION_PROMPT
    return f"{movement.rstrip('. ')}. {ANIMATION_GUARD}"


def animation_seconds() -> int:
    """Duração do clipe animado (ANIMATION_CLIP_SECONDS, entre 5 e 15 s). Curto de propósito: clipe longo inventa mais."""
    return max(MIN_CLIP_SECONDS, min(MAX_CLIP_SECONDS, settings.ANIMATION_CLIP_SECONDS))


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
