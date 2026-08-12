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


@app.middleware("http")
async def no_cachear_la_interfaz(request, call_next):
    """Evita que el navegador sirva una version antigua de la interfaz.

    Entrada:
        request: peticion entrante.
        call_next: siguiente manejador de la cadena.

    Salida:
        La respuesta, con la cabecera de cache anulada cuando se trata de la
        interfaz.

    Funcionalidad:
        La interfaz es estatica y se regenera al editar los archivos, sin paso
        de compilacion que ponga una huella en el nombre. Sin esto el navegador
        conserva el HTML y los modulos anteriores y la pantalla sigue mostrando
        la version vieja despues de un cambio, que es indistinguible de que el
        cambio no se haya aplicado.
    """
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response


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
