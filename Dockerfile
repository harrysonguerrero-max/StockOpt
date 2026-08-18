# Etapa de construcción
FROM public.ecr.aws/docker/library/python:3.12-slim-bookworm AS builder

# Instalar uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Configurar directorio de trabajo
WORKDIR /app

# git es necesario para resolver la URL git+https del mlops-sdk: uv delega en el
# binario de git y la imagen slim no lo trae. Solo vive en esta etapa; la imagen
# final no lo hereda.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Habilitar compilación de bytecode
ENV UV_COMPILE_BYTECODE=1

# Copiar archivos de dependencias
COPY pyproject.toml .

# Instalar dependencias
# --no-dev: Excluye dependencias de desarrollo (grupo 'dev' en pyproject.toml)
# --frozen: Usa exactament las versiones del lockfile (si existiera) o pyproject.toml
# --no-install-project: Solo instala dependencias, no el proyecto en sí (cacheable)
RUN uv sync --frozen --no-dev --no-install-project || uv sync --no-dev --no-install-project

ARG GITLAB_DEPLOY_USER=""
ARG GITLAB_DEPLOY_TOKEN=""

# Antes de instalar se informa de si las credenciales llegaron, para poder
# distinguir "el secreto no llego" de "el repositorio fallo". Se imprime la
# presencia y la longitud del token, nunca su valor: el registro de CodeBuild
# queda en CloudWatch y ahi no puede aparecer una credencial.
RUN if [ -n "$GITLAB_DEPLOY_USER" ] && [ -n "$GITLAB_DEPLOY_TOKEN" ]; then \
      echo "[mlops-sdk] usuario: presente | token: presente (${#GITLAB_DEPLOY_TOKEN} caracteres)"; \
      uv pip install "git+https://${GITLAB_DEPLOY_USER}:${GITLAB_DEPLOY_TOKEN}@gitlab.digitalcoedevops.com/harryson.guerrero/mlops-sdk.git@v0.5.0"; \
    else \
      echo "[mlops-sdk] usuario: $(if [ -n "$GITLAB_DEPLOY_USER" ]; then echo presente; else echo AUSENTE; fi) | token: $(if [ -n "$GITLAB_DEPLOY_TOKEN" ]; then echo presente; else echo AUSENTE; fi)"; \
      echo "[mlops-sdk] no se instala; la verificacion del buildspec fallara a proposito"; \
    fi

COPY . .

# --inexact es obligatorio aqui. Por defecto `uv sync` deja el entorno
# exactamente igual al lockfile y desinstala todo lo que sobre. El mlops-sdk se
# instala con `uv pip install` desde GitLab, asi que no figura en
# pyproject.toml: sin este flag, este paso lo borraba justo despues de haberlo
# instalado bien. En el log se veia la instalacion correcta y luego el import
# fallaba en la imagen final, que es el sintoma mas confuso posible.
RUN uv sync --no-dev --inexact

# Etapa final
FROM public.ecr.aws/docker/library/python:3.12-slim-bookworm

# Copiar el entorno virtual desde el builder
COPY --from=builder /app/.venv /app/.venv

# Configurar PATH para usar el venv
ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Copiar código fuente
COPY app ./app

# Las graficas y el informe del pipeline viven fuera de app/. Sin esto,
# /pipeline/stages y /training/metrics responden 503 en el contenedor y la vista
# de modelo sale vacia, aunque funcione en local.
COPY artifacts ./artifacts

# Exponer puerto
EXPOSE 8000

# Comando de ejecución
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
