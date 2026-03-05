import logging
from fastapi import APIRouter, HTTPException, Depends

from app.db.database import scalar
from app.api.deps import require_role

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/db/ping", tags=["system"])
def db_ping(_user=Depends(require_role("admin"))):
    """
    Verifica conectividad a MySQL haciendo un SELECT 1.
    Protegido: solo rol admin.
    """
    try:
        value = scalar("SELECT 1")
        return {"db": "ok", "value": value}
    except Exception as exc:
        logger.exception("DB ping failed")
        raise HTTPException(status_code=500, detail="DB connection failed") from exc