"""python -m engine"""
from __future__ import annotations

import uvicorn

from .config import settings

if __name__ == "__main__":
    uvicorn.run(
        "engine.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )
