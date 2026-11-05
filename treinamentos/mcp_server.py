"""
Conector MCP do portal, para o Claude (Claude.ai / Claude Code) operar a geração de vídeos.

Implementa o mínimo do MCP sobre HTTP ("Streamable HTTP", respostas em JSON): initialize, ping,
tools/list e tools/call. Não depende de SDK.

Autenticação (o conector fica desligado enquanto MCP_TOKEN estiver vazio):
  - /mcp/<MCP_TOKEN>/              a chave no endereço (o Claude da web não envia cabeçalho próprio)
  - /mcp/ + "Authorization: Bearer <MCP_TOKEN>"   (Claude Code e outros clientes)
"""
import hmac
import json
import logging
from urllib.parse import urlparse

from django.conf import settings
from django.http import Http404, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .models import TrainingVideo
from .services.pipeline import generation_params, save_generated_video

logger = logging.getLogger(__name__)
Status = TrainingVideo.Status

SUPPORTED_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
WAITING = (Status.AWAITING_VIDEO, Status.GENERATING_HEYGEN)

INSTRUCTIONS = (
    "Portal Carmel Treinamentos. Fluxo para gerar os vídeos aprovados: "
    "1) list_awaiting_videos para ver os roteiros aprovados. "
    "2) Para cada item, gere o vídeo na HeyGen (create_video_from_avatar) com o roteiro EXATO, o avatar_id e o voice_id "
    "devolvidos, sem reescrever o texto. "
    "3) mark_video_rendering com o video_id da HeyGen. "
    "4) Acompanhe com get_video da HeyGen até 'completed' (nunca recrie o vídeo para verificar). "
    "5) save_generated_video com o link do MP4, o ID da HeyGen e a duração: o portal salva no Drive e publica."
)


class ToolError(Exception):
    """Erro esperado de uma ferramenta; volta ao Claude como resultado com isError."""


def _get_video(args: dict) -> TrainingVideo:
    try:
        video_id = int(args.get("video_id"))
    except (TypeError, ValueError):
        raise ToolError("Informe video_id (número do item na fila do portal).")
    try:
        return TrainingVideo.objects.select_related("department").get(id=video_id)
    except TrainingVideo.DoesNotExist:
        raise ToolError(f"Item {video_id} não encontrado.")


def _validate_video_url(url) -> str:
    parsed = urlparse(str(url or ""))
    host = (parsed.hostname or "").lower()
    allowed = settings.MCP_ALLOWED_VIDEO_HOSTS
    if parsed.scheme != "https" or not any(host == h or host.endswith("." + h) for h in allowed):
        raise ToolError(f"O link do vídeo precisa ser https e de um destes domínios: {', '.join(allowed)}.")
    return str(url)


def _describe(video: TrainingVideo) -> dict:
    params = generation_params(video)
    return {
        "video_id": video.id,
        "setor": video.department.name,
        "setor_codigo": video.department.code,
        "titulo": video.title,
        "status": video.get_status_display(),
        "avatar_id": params["avatar_id"],
        "voice_id": params["voice_id"],
        "heygen_video_id": video.heygen_video_id,
        "caracteres": len(video.script_text),
        "roteiro": video.script_text,
    }


def tool_list_awaiting_videos(args: dict) -> dict:
    videos = TrainingVideo.objects.filter(status__in=WAITING).select_related("department").order_by("created_at")
    if args.get("setor"):
        videos = videos.filter(department__code=str(args["setor"]))
    items = [_describe(v) for v in videos]
    return {"total": len(items), "videos": items}


def tool_mark_video_rendering(args: dict) -> dict:
    video = _get_video(args)
    heygen_id = str(args.get("heygen_video_id") or "").strip()
    if not heygen_id:
        raise ToolError("Informe heygen_video_id.")
    if video.status not in WAITING:
        raise ToolError(f"O item está em '{video.get_status_display()}'; só itens aguardando vídeo podem ser marcados.")
    video.set_status(
        Status.GENERATING_HEYGEN, "Renderizando vídeo com Avatar Digital na HeyGen...", heygen_video_id=heygen_id
    )
    return {"video_id": video.id, "status": video.get_status_display()}


def tool_save_generated_video(args: dict) -> dict:
    video = _get_video(args)
    url = _validate_video_url(args.get("video_url"))
    try:
        duration = float(args.get("duration_seconds") or 0)
    except (TypeError, ValueError):
        raise ToolError("duration_seconds precisa ser um número.")
    publish = args.get("publish", True) is not False

    try:
        file_id = save_generated_video(
            video,
            video_url=url,
            heygen_video_id=str(args.get("heygen_video_id") or ""),
            duration=duration,
            thumbnail_url=str(args.get("thumbnail_url") or ""),
            publish=publish,
        )
    except (ValueError, RuntimeError) as exc:
        raise ToolError(str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("MCP: falha ao salvar o vídeo %s", video.id)
        raise ToolError(f"Falha ao salvar o vídeo no Drive: {exc}")
    video.refresh_from_db()
    return {
        "video_id": video.id,
        "drive_file_id": file_id,
        "status": video.get_status_display(),
        "publicado": video.status == Status.COMPLETED,
        "mensagem": video.status_message,
    }


def tool_get_video_status(args: dict) -> dict:
    video = _get_video(args)
    return {
        "video_id": video.id,
        "titulo": video.title,
        "status": video.get_status_display(),
        "mensagem": video.status_message,
        "heygen_video_id": video.heygen_video_id,
        "salvo_no_drive": bool(video.drive_video_id),
    }


_ID = {"type": "integer", "description": "Número do item na fila do portal (video_id devolvido por list_awaiting_videos)."}

TOOLS = {
    "list_awaiting_videos": {
        "handler": tool_list_awaiting_videos,
        "description": (
            "Lista os roteiros já aprovados que aguardam a geração do vídeo, com o roteiro exato, o avatar_id e o "
            "voice_id a usar na HeyGen."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"setor": {"type": "string", "description": "Código do setor para filtrar (opcional), ex.: rh."}},
        },
    },
    "mark_video_rendering": {
        "handler": tool_mark_video_rendering,
        "description": "Registra que a geração começou na HeyGen (a fila do portal passa a mostrar 'HeyGen Renderizando').",
        "inputSchema": {
            "type": "object",
            "properties": {
                "video_id": _ID,
                "heygen_video_id": {"type": "string", "description": "video_id devolvido pela HeyGen ao criar o vídeo."},
            },
            "required": ["video_id", "heygen_video_id"],
        },
    },
    "save_generated_video": {
        "handler": tool_save_generated_video,
        "description": (
            "Com o vídeo já 'completed' na HeyGen, o portal baixa o MP4, salva na pasta Vídeos do setor no Drive "
            "e (por padrão) publica no catálogo. Só aceita links https da HeyGen."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "video_id": _ID,
                "video_url": {"type": "string", "description": "video_url do MP4 devolvido por get_video da HeyGen."},
                "heygen_video_id": {"type": "string", "description": "ID do vídeo na HeyGen."},
                "duration_seconds": {"type": "number", "description": "Duração em segundos (campo duration de get_video)."},
                "thumbnail_url": {"type": "string", "description": "Link da miniatura (opcional)."},
                "publish": {
                    "type": "boolean",
                    "description": "true (padrão): publica já. false: só salva no Drive; entra no catálogo ao sincronizar.",
                },
            },
            "required": ["video_id", "video_url"],
        },
    },
    "get_video_status": {
        "handler": tool_get_video_status,
        "description": "Consulta o status de um item no portal.",
        "inputSchema": {"type": "object", "properties": {"video_id": _ID}, "required": ["video_id"]},
    },
}


def _rpc_result(msg_id, result) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _rpc_error(msg_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _handle(msg):
    """Trata uma mensagem JSON-RPC. Devolve a resposta, ou None quando não há resposta (notificações)."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return _rpc_error(None, -32600, "Requisição inválida.")
    if "method" not in msg:
        return None  # resposta de um cliente a algo nosso: não usamos
    method, params = msg["method"], msg.get("params") or {}
    msg_id = msg.get("id")
    if "id" not in msg:
        return None  # notificação (ex.: notifications/initialized)

    if method == "initialize":
        requested = params.get("protocolVersion")
        return _rpc_result(msg_id, {
            "protocolVersion": requested if requested in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "carmel-treinamentos", "version": "1.0.0"},
            "instructions": INSTRUCTIONS,
        })
    if method == "ping":
        return _rpc_result(msg_id, {})
    if method == "tools/list":
        tools = [
            {"name": name, "description": t["description"], "inputSchema": t["inputSchema"]}
            for name, t in TOOLS.items()
        ]
        return _rpc_result(msg_id, {"tools": tools})
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        tool = TOOLS.get(name)
        if not tool:
            return _rpc_error(msg_id, -32602, f"Ferramenta desconhecida: {name}")
        logger.info("MCP tools/call %s item=%s", name, args.get("video_id", "-"))
        try:
            data = tool["handler"](args)
            is_error = False
        except ToolError as exc:
            data, is_error = {"erro": str(exc)}, True
        return _rpc_result(msg_id, {
            "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
            "isError": is_error,
        })
    return _rpc_error(msg_id, -32601, f"Método não suportado: {method}")


def _authorized(request, token) -> bool:
    configured = settings.MCP_TOKEN.encode("utf-8")
    if token is not None:
        return hmac.compare_digest(token.encode("utf-8"), configured)
    header = request.headers.get("Authorization", "")
    supplied = header[7:].strip() if header.lower().startswith("bearer ") else ""
    return bool(supplied) and hmac.compare_digest(supplied.encode("utf-8"), configured)


@csrf_exempt
def mcp_endpoint(request, token=None):
    if not settings.MCP_TOKEN:
        raise Http404  # conector desligado
    if not _authorized(request, token):
        if token is not None:
            raise Http404  # não confirma a existência do endereço a quem não tem a chave
        response = HttpResponse("Não autorizado.", status=401)
        response["WWW-Authenticate"] = 'Bearer realm="carmel-treinamentos"'
        return response
    if request.method != "POST":
        response = HttpResponse(status=405)
        response["Allow"] = "POST"
        return response

    try:
        payload = json.loads(request.body or b"")
    except ValueError:
        return JsonResponse(_rpc_error(None, -32700, "JSON inválido."), status=400)

    if isinstance(payload, list):
        replies = [r for r in (_handle(m) for m in payload) if r is not None]
        return JsonResponse(replies, safe=False) if replies else HttpResponse(status=202)
    reply = _handle(payload)
    return JsonResponse(reply) if reply is not None else HttpResponse(status=202)
