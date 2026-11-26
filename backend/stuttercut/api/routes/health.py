import sys
from typing import Any

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/health")
def health(request: Request) -> dict[str, Any]:
    """``platform`` lets the UI say Finder or Explorer; ``worker`` = the watchdog's last sample."""
    worker = getattr(request.app.state, "worker", None)
    return {"status": "ok", "platform": sys.platform, "worker": getattr(worker, "stats", None)}
