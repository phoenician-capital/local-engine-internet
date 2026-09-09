"""Layer 1 switch + status. Layer 2 is intelligence (auto) once enabled."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from .. import runtime
from ..plugin import plugin_status
from ..search.merge import configured_providers

router = APIRouter()


class PluginUpdate(BaseModel):
    enabled: bool


@router.get("/v1/plugin")
async def get_plugin() -> dict[str, Any]:
    status = plugin_status()
    status["providers"] = configured_providers()
    status["search_ready"] = bool(configured_providers()) and bool(status["enabled"])
    return status


@router.post("/v1/plugin")
async def set_plugin(body: PluginUpdate) -> dict[str, Any]:
    runtime.plugin_enabled = bool(body.enabled)
    return await get_plugin()
