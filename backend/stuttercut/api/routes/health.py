import sys

from fastapi import APIRouter

router = APIRouter()


@router.get("/api/health")
def health() -> dict[str, str]:
    """``platform`` lets the UI say Finder (macOS) or Explorer (Windows)."""
    return {"status": "ok", "platform": sys.platform}
