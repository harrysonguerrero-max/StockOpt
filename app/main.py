"""Arranque de la aplicacion web de SupplyOpt.

Funcionalidad:
    Monta la API de recomendaciones y sirve la interfaz de compras como sitio
    estatico, de modo que todo el MVP corra en un unico proceso y una unica
    imagen de contenedor.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import settings

WEB_DIR = Path(__file__).resolve().parent / "web"

app = FastAPI(title=settings.PROJECT_NAME, openapi_url=f"{settings.API_V1_STR}/openapi.json")

if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(router, prefix=settings.API_V1_STR)

if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/", include_in_schema=False)
def root():
    """Entrega la interfaz de compras.

    Entrada:
        Ninguna.

    Salida:
        La pagina principal, o un mensaje de bienvenida si aun no se construye
        la interfaz.

    Funcionalidad:
        Deja la raiz apuntando a la pantalla que usa el comprador, en lugar de a
        una respuesta tecnica.
    """
    index = WEB_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return {
        "message": f"Bienvenido a {settings.PROJECT_NAME}",
        "docs": f"{settings.API_V1_STR}/docs",
    }
