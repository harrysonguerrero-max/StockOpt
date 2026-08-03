# Etapa de construcción
FROM public.ecr.aws/docker/library/python:3.12-slim-bookworm AS builder

# Instalar uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Configurar directorio de trabajo
WORKDIR /app

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

RUN if [ -n "$GITLAB_DEPLOY_USER" ] && [ -n "$GITLAB_DEPLOY_TOKEN" ]; then \
      uv pip install "git+https://${GITLAB_DEPLOY_USER}:${GITLAB_DEPLOY_TOKEN}@gitlab.digitalcoedevops.com/harryson.guerrero/mlops-sdk.git@v0.1.2"; \
    else \
      echo "Skipping mlops-sdk installation: missing GitLab credentials"; \
    fi

COPY . .
RUN uv sync --no-dev

# Etapa final
FROM public.ecr.aws/docker/library/python:3.12-slim-bookworm

# Copiar el entorno virtual desde el builder
COPY --from=builder /app/.venv /app/.venv

# Configurar PATH para usar el venv
ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Copiar código fuente
COPY app ./app

# Exponer puerto
EXPOSE 8000

# Comando de ejecución
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
