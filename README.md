# StockOpt

Plantilla de producción para proyectos Python 3.12+ utilizando **uv** para la gestión de paquetes, **Docker** para la contenedorización y una arquitectura completa en **AWS** (ECS + Amplify).

## ⚡ Stack Tecnológico

- **Core:** FastAPI, Uvicorn.
- **Gestor de Paquetes:** `uv` (Rendimiento ultra rápido).
- **Infraestructura:** Docker Multi-stage, AWS ECS (Fargate), AWS Amplify.
- **CI/CD:** GitLab CI + AWS CodeBuild.
- **Calidad:** Ruff (Linter/Formatter).

---

## 🛠️ Requisitos Previos

Asegúrate de tener instalado lo siguiente antes de comenzar:

1. **[uv](https://github.com/astral-sh/uv):** Gestor de paquetes.
2. **[Docker Desktop](https://www.docker.com/products/docker-desktop/):** Para ejecución local y construcción de imágenes.
3. **[AWS CLI](https://aws.amazon.com/cli/):** Configurado con `aws configure`.
4. **PowerShell (Core o Windows):** Para ejecutar los scripts de despliegue en `deployment/`.

---

## 🚀 Inicio Rápido (Desarrollo Local)

### 1. Instalación y Entorno
Este proyecto utiliza el stack **standard**. Sincroniza el entorno para instalar todas las dependencias (dev y prod):

```bash
uv sync
```

### 2. Ejecuta el Servidor

Puedes activar el entorno virtual o usar `uv run` directamente:

```bash
uv run uvicorn app.main:app --reload
```

El servidor estará disponible en ``http://localhost:8000``.

---

## 🐳 Docker 

El proyecto incluye un ``Dockerfile`` multi-etapa optimizado. El archivo ``compose.yml`` monta el directorio ./app como un volumen, habilitando el Hot-Reload.

### Ejecutar con Docker Compose (Hot-reload habilitado):
```bash
docker compose up --build
```

### Construir y probar la imagen de producción manualmente:
```bash
docker build -t stockopt .
docker run -p 8000:8000 stockopt
```

**Nota:** El ``Dockerfile`` instala solo las dependencias de producción por defecto. Si requieres grupos adicionales, modifica el paso ``uv sync`` dentro del Dockerfile.

---

## 📂 Estructura del Proyecto

```text
.
├── app/
│   ├── api/
│   │   └── routes.py                  # Endpoints (Rutas FastAPI)
│   ├── core/
│   │   └── config.py                  # Configuración global (Env vars, Logging)
│   ├── services/
│   │   └── ...                        # Lógica de negocio pura (Desacoplada de HTTP)
│   └── main.py                        # Entrypoint (CORS, Middleware)
├── deployment/
│   ├── aws-service-deployment.ps1     # Script de despliegue de servicios AWS
│   ├── redeploy.ps1                   # Script de CICD (API y Frontend)
│   └── ...                            # Archivos de configuración
├── frontend/                          # Source del Frontend (npm run build compatible)
├── pyproject.toml                     # Dependencias
├── Dockerfile
├── docker-compose.yml
├── buildspec.yml                      # Constructor de imágenes Docker en CodeBuild
├── .gitlab-ci.yml                     # GitLab CICD
├── .gitignore
└── .dockerignore
```

---

## Variables de entorno

Este proyecto usa `MLFLOW_TRACKING_URI` para decidir dónde se guardan los experimentos y artefactos de MLflow.

### Para desarrollo local
Si quieres probar en tu máquina y registrar en un MLflow local, usa:

```bash
export MLFLOW_TRACKING_URI=http://localhost:5000
```

### Para usar el MLflow de la nube
Si quieres registrar en el MLflow centralizado del equipo, usa la URL del tracking server de la nube:

```bash
export MLFLOW_TRACKING_URI=http://<tu-mlflow-cloud>:5000
```

### Flujo esperado
- Si `MLFLOW_TRACKING_URI` apunta a `localhost`, el entrenamiento registra en MLflow local.
- Si apunta a la nube, el entrenamiento registra en el MLflow compartido.

### 🏗️ Guía de Implementación
- ``app/main.py``: Es exclusivamente el **punto de entrada**. Úsalo solo para configurar middlewares, CORS y montar rutas. No escribas lógica de negocio aquí.
- ``app/services/``: Aquí reside el corazón de la aplicación. Las funciones deben ser puras y agnósticas al framework HTTP.
- ``app/api/``: La capa de interfaz. Se encarga de recibir la petición HTTP, llamar al servicio correspondiente y devolver la respuesta.

### ☁️ Infraestructura y Despliegue (AWS)

El despliegue se maneja mediante scripts de PowerShell ubicados en ``deployment/``.

#### Scripts de Despliegue

1. `aws-service-deployment.ps1`:  
   Este script es el **inicializador**. Crea toda la infraestructura base necesaria en AWS. Requiere un rol de AWS CLI con permisos de Administrador o suficientes para crear VPCs, ECS, ECR, etc.
2. `redeploy.ps1`:  
   Este script es el inicializador. Crea toda la infraestructura base necesaria en AWS. Requiere un rol de AWS CLI con permisos de Administrador o suficientes para crear VPCs, ECS, ECR, etc.

#### Arquitectura de Recursos

<details><summary><b>👁️ Ver lista detallada de servicios creados</b></summary>

##### Networking & Seguridad
- VPC: Configurada con 2 subnets privadas (AZ 1a/1b), Internet Gateway y Route Tables.
- ALB (Application Load Balancer): Target groups y Listeners configurados.
- Seguridad: Security Groups específicos para el ALB y los contenedores.
##### Cómputo & Contenedores
- ECS Cluster: Ejecución de tareas Fargate.
- ECR Repository: Almacenamiento de imágenes Docker.
- Auto-scaling: Configurado por horario (9:00 - 17:00 CST) para optimización de costos.
##### Frontend & Almacenamiento
- AWS Amplify: Hosting del frontend.
- S3 Bucket: Almacenamiento de assets estáticos.
##### CI/CD & Observabilidad
- CodeBuild: Proyecto para construcción de imágenes.
- CloudWatch: Grupo de logs centralizado.
- IAM Roles: Roles de ejecución y tarea con principio de menor privilegio.
</details>

---

### 🔄 Workflow de Desarrollo & CI/CD

#### Gestión de Dependencias
- **Agregar librería:** ``uv add <paquete>``
- **Agregar herramienta dev:** ``uv add --dev <paquete>``
- **Actualizar entorno:** ``uv sync``
#### Calidad de Código (Linting)
El pipeline fallará si el código no cumple los estándares. Antes de hacer commit, ejecuta:
```bash
ruff format       # Formateo automático
ruff check --fix  # Linter y corrección de errores
```
#### Pipeline de GitLab
El archivo ``.gitlab-ci.yml`` activa despliegues automáticos al hacer push a las ramas:
- ``dev``
- ``develop``
- ``development``
