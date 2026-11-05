import logging
import os
import uuid
from typing import Any, Dict, Optional

import httpx
from django.conf import settings

from treinamentos.models import SystemSetting

logger = logging.getLogger(__name__)

# Limite de caracteres aceito pela HeyGen em um único bloco de fala.
MAX_SCRIPT_CHARS = 5000

MOCK_PREFIX = "mock-"
MOCK_RESULT = {
    "status": "completed",
    "video_url": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4",
    "thumbnail_url": "https://images.unsplash.com/photo-1542314831-068cd1dbfeeb?w=800&auto=format&fit=crop&q=80",
    "duration": 95.0,
    "error": None,
}


class HeyGenError(Exception):
    pass


class HeyGenService:
    @staticmethod
    def get_api_key() -> str:
        return SystemSetting.get_val("heygen_api_key", os.getenv("HEYGEN_API_KEY", ""))

    @classmethod
    def is_mock_mode(cls) -> bool:
        mode = SystemSetting.get_val("heygen_mock_mode", os.getenv("HEYGEN_MOCK_MODE", "true"))
        if mode.lower() in ("true", "1", "yes", "on"):
            return True
        return not cls.get_api_key()

    @staticmethod
    def is_mock_id(video_id: str) -> bool:
        return (video_id or "").startswith(MOCK_PREFIX)

    @classmethod
    def _headers(cls) -> Dict[str, str]:
        api_key = cls.get_api_key()
        if not api_key:
            raise HeyGenError("Chave de API da HeyGen não configurada (HEYGEN_API_KEY).")
        return {"X-Api-Key": api_key, "Content-Type": "application/json", "Accept": "application/json"}

    @classmethod
    def generate_video(
        cls,
        script_text: str,
        avatar_id: Optional[str] = None,
        voice_id: Optional[str] = None,
        title: str = "Treinamento Carmel",
    ) -> Dict[str, Any]:
        if cls.is_mock_mode():
            logger.info("[HeyGen MOCK] Simulando renderização para: %s", title)
            return {"video_id": f"{MOCK_PREFIX}{uuid.uuid4().hex[:12]}", "mock": True}

        avatar = avatar_id or os.getenv("DEFAULT_AVATAR_ID", "")
        voice = voice_id or os.getenv("DEFAULT_VOICE_ID", "")
        if not avatar or not voice:
            raise HeyGenError(
                "Avatar ou voz da HeyGen não definidos. Configure no setor (Django Admin) "
                "ou DEFAULT_AVATAR_ID / DEFAULT_VOICE_ID no .env."
            )

        payload = {
            "title": title[:200],
            "video_inputs": [
                {
                    "character": {"type": "avatar", "avatar_id": avatar, "avatar_style": "normal"},
                    "voice": {
                        "type": "text",
                        "input_text": script_text,
                        "voice_id": voice,
                        "speed": 1.0,
                    },
                    "background": {"type": "color", "value": "#FAF8F5"},
                }
            ],
            "dimension": {"width": 1280, "height": 720},
        }

        with httpx.Client(timeout=60.0) as client:
            resp = client.post(f"{settings.HEYGEN_API_URL}/v2/video/generate", headers=cls._headers(), json=payload)
        if resp.status_code != 200:
            raise HeyGenError(f"Erro na HeyGen API ({resp.status_code}): {resp.text[:500]}")

        data = resp.json()
        video_id = (data.get("data") or {}).get("video_id")
        if not video_id:
            raise HeyGenError(f"Resposta inesperada da HeyGen: {str(data)[:500]}")
        return {"video_id": video_id, "mock": False}

    @classmethod
    def check_video_status(cls, video_id: str) -> Dict[str, Any]:
        """
        Retorna {status, video_url, thumbnail_url, duration, error}.
        status ∈ {pending, waiting, processing, completed, failed}.
        """
        if cls.is_mock_id(video_id):
            return dict(MOCK_RESULT)

        with httpx.Client(timeout=30.0) as client:
            resp = client.get(
                f"{settings.HEYGEN_API_URL}/v1/video_status.get",
                params={"video_id": video_id},
                headers=cls._headers(),
            )
        if resp.status_code != 200:
            raise HeyGenError(f"Erro ao consultar HeyGen ({resp.status_code}): {resp.text[:500]}")

        data = resp.json().get("data") or {}
        error = data.get("error")
        if isinstance(error, dict):
            error = error.get("message") or error.get("detail") or str(error)
        return {
            "status": (data.get("status") or "").lower(),
            "video_url": data.get("video_url") or "",
            "thumbnail_url": data.get("thumbnail_url") or "",
            "duration": float(data.get("duration") or 0),
            "error": error,
        }
