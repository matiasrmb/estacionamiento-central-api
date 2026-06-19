from typing import Dict, Any, Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError

from app.core.security import decode_token

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> Dict[str, Any]:
    """
    Extrae y valida JWT desde Authorization: Bearer <token>.
    Retorna claims del token como dict.
    """
    if creds is None or not creds.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )

    token = creds.credentials
    try:
        claims = decode_token(token)
        return claims
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )


def require_role(*allowed_roles: str) -> Callable:
    """
    Dependency factory para restringir acceso por rol.
    Uso: Depends(require_role("admin"))
    """
    role_alias = {
        "administrador": "admin",
        "admin": "admin",
        "operador": "operador",
    }

    normalized_allowed = {role_alias.get(r.strip().lower(), r.strip().lower()) for r in allowed_roles}

    def _checker(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
        raw_role = (user.get("rol") or "").strip().lower()
        role = role_alias.get(raw_role, raw_role)

        if role not in normalized_allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden for this role",
            )
        return user

    _checker.allowed_roles = normalized_allowed
    return _checker
