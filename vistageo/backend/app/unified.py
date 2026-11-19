import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.main import app as api


def create_unified_app(frontend: Path) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if not (frontend / "index.html").is_file() or not (frontend / "assets").is_dir():
            raise RuntimeError("La compilación del frontend no está disponible")
        async with api.router.lifespan_context(api):
            yield

    application = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    application.mount("/api", api)
    application.mount("/assets", StaticFiles(directory=frontend / "assets", check_dir=False), name="assets")

    @application.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def frontend_page(path: str) -> FileResponse:
        public_files = {"index.html", "favicon.svg", "icons.svg", "manifest.webmanifest", "service-worker.js"}
        if path in public_files:
            target = frontend / path
            if not target.is_file():
                raise HTTPException(status_code=404, detail="Archivo no encontrado")
        elif "." in path.rsplit("/", 1)[-1]:
            raise HTTPException(status_code=404, detail="Archivo no encontrado")
        else:
            target = frontend / "index.html"
        return FileResponse(target, headers={"Cache-Control": "no-cache"})

    return application


default_frontend = Path(__file__).resolve().parents[2] / "frontend" / "dist"
app = create_unified_app(Path(os.environ.get("FRONTEND_DIST", str(default_frontend))))
