from fastapi import APIRouter
from app.api.v1.endpoints import health, db_ping, auth
from app.api.v1.endpoints import ingresos, activos, salidas, configuracion, tarifas

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(db_ping.router)

# MVP
api_router.include_router(ingresos.router)
api_router.include_router(activos.router)
api_router.include_router(salidas.router)
api_router.include_router(configuracion.router)
api_router.include_router(tarifas.router)
