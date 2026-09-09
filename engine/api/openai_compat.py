"""OpenAI discovery endpoints that Cursor / Continue / Open WebUI probe first."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..config import settings
from ..connect import connection_info
from ..plugin import plugin_status

router = APIRouter()


def _model_card(model_id: str) -> dict:
    return {
        "id": model_id,
        "object": "model",
        "created": 0,
        "owned_by": "local-engine-internet",
    }


@router.get("/v1/models")
@router.get("/models")
async def list_models() -> dict:
    return {"object": "list", "data": [_model_card(settings.upstream_model)]}


@router.get("/v1/models/{model_id}")
@router.get("/models/{model_id}")
async def get_model(model_id: str) -> dict:
    if model_id != settings.upstream_model:
        raise HTTPException(status_code=404, detail="Unknown model")
    return _model_card(model_id)


@router.get("/v1")
async def openai_root() -> dict:
    info = connection_info()
    return {
        "object": "local-engine-internet",
        "search_ready": info["search_ready"],
        "plugin": plugin_status(),
        "providers": info["providers"],
        "openai_base_url": info["openai_base_url"],
        "model": info["model"],
        "endpoints": {
            "chat": "/v1/chat/completions",
            "models": "/v1/models",
            "search": "/v1/search",
            "fetch": "/v1/fetch",
            "plugin": "/v1/plugin",
            "ui": "/ui",
        },
        "connect": info["snippets"],
        "notes": info["notes"],
    }
