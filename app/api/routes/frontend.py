from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse


BASE_DIR = Path(__file__).resolve().parents[3]
FRONTEND_DIR = BASE_DIR / "frontend"

router = APIRouter()


@router.get("/")
def frontend() -> FileResponse:
    index = FRONTEND_DIR / "index.html"

    if not index.exists():
        raise HTTPException(
            status_code=404,
            detail="Frontend not found.",
        )

    return FileResponse(index)


@router.get("/styles.css")
def styles() -> FileResponse:
    css = FRONTEND_DIR / "styles.css"

    if not css.exists():
        raise HTTPException(
            status_code=404,
            detail="styles.css not found.",
        )

    return FileResponse(css, media_type="text/css")


@router.get("/app.js")
def javascript() -> FileResponse:
    js = FRONTEND_DIR / "app.js"

    if not js.exists():
        raise HTTPException(
            status_code=404,
            detail="app.js not found.",
        )

    return FileResponse(js, media_type="application/javascript")
