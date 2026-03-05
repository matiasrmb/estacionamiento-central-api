from fastapi import APIRouter

router = APIRouter()


@router.get("/health", tags=["system"])
def health():
    """
    Healthcheck simple para verificar que la API está viva.
    """
    return {"status": "ok"}