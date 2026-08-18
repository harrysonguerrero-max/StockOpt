"""Arranque de la aplicacion web de SupplyOpt.

Funcionalidad:
    Monta la API de recomendaciones y, si esta compilada, tambien la interfaz.

    La interfaz vive en `frontend/` y se compila con Vite a `frontend/dist`.
    Sirviendola desde aqui, todo el MVP corre en un unico proceso, que es lo mas
    comodo en local y en `docker compose`. En el despliegue de AWS no ocurre:
    Amplify publica `dist` y este contenedor queda como API sola, asi que el
    montaje es condicional y su ausencia no es un error.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import settings

WEB_DIR = Path(__file__).resolve().parents[1] / "frontend" / "dist"

app = FastAPI(title=settings.PROJECT_NAME, openapi_url=f"{settings.API_V1_STR}/openapi.json")

if settings.BACKEND_CORS_ORIGINS or settings.BACKEND_CORS_ORIGIN_REGEX:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS,
        allow_origin_regex=settings.BACKEND_CORS_ORIGIN_REGEX,
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
        Los archivos compilados llevan huella en el nombre y pueden cachearse
        sin riesgo, pero `index.html` no: es quien apunta a esa huella. Si el
        navegador lo conserva, la pantalla sigue cargando la version anterior
        despues de un despliegue, que es indistinguible de que el despliegue no
        haya ocurrido.
    """
    response = await call_next(request)
    if request.url.path == "/":
        response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response


ASSETS_DIR = WEB_DIR / "assets"

if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")


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
