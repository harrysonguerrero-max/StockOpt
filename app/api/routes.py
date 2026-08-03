from fastapi import APIRouter
from app.services import demo_service

router = APIRouter()


@router.get("/health")
def health_check():
    return {"status": "ok"}


@router.get("/items/{item_id}")
def read_item(item_id: int):
    """
    Example endpoint using the service layer.
    """
    return demo_service.process_item(item_id)
