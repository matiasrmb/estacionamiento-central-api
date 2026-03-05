import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifica una contraseña contra el hash bcrypt almacenado.
    """
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        logger.exception("Password verification failed")
        return False


def create_access_token(subject: str, extra_claims: Dict[str, Any]) -> str:
    """
    Crea un JWT de acceso.
    - subject: normalmente el username
    - extra_claims: ej. rol, id_usuario
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.jwt_access_token_expire_minutes)

    payload = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        **extra_claims,
    }

    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token


def decode_token(token: str) -> Dict[str, Any]:
    """
    Decodifica y valida JWT. Lanza JWTError si es inválido/expirado.
    """
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])