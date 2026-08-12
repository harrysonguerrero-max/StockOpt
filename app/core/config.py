"""Configuracion de la aplicacion.

Funcionalidad:
    Reune los pocos parametros que dependen del entorno y no del dominio: el
    nombre del producto, el prefijo de la API, los origenes autorizados para
    peticiones desde otro dominio y las credenciales de los servicios externos.

    Los parametros de negocio no viven aqui sino al inicio del modulo que los
    usa, de modo que cada regla se lea junto al codigo que la aplica.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Parametros de entorno de la aplicacion.

    Funcionalidad:
        Se leen del archivo .env cuando existe y caen a los valores declarados
        aqui cuando no. Los origenes autorizados incluyen el puerto en que corre
        la propia aplicacion y el puerto habitual de un frontend en desarrollo,
        para poder servir la interfaz por separado durante el trabajo local.
    """

    PROJECT_NAME: str = "SupplyOpt"
    API_V1_STR: str = "/api/v1"

    BACKEND_CORS_ORIGINS: list[str] = [
        "http://localhost",
        "http://localhost:8000",
        "http://localhost:3000",
        "http://localhost:5173",
    ]
    MLFLOW_TRACKING_URI: str | None = "http://localhost:5000"
    GEMINI_API_KEY: str | None = None

    class Config:
        """Ajustes de lectura del entorno.

        Funcionalidad:
            Exige que los nombres coincidan en mayusculas y minusculas y toma
            .env como origen, para que el despliegue pueda sobreescribir
            cualquier valor sin tocar el codigo.
        """

        case_sensitive = True
        env_file = ".env"


settings = Settings()
