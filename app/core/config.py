from pydantic_settings import BaseSettings
from typing import List, Optional


class Settings(BaseSettings):
    PROJECT_NAME: str = "StockOpt"
    API_V1_STR: str = "/api/v1"

    # CORS Configuration
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost",
        "http://localhost:8000",
        "http://localhost:3000",  # Common frontend port
    ]
    MLFLOW_TRACKING_URI: Optional[str] = "http://localhost:5000"
    GEMINI_API_KEY: Optional[str] = None
    class Config:
        case_sensitive = True
        env_file = ".env"


settings = Settings()
