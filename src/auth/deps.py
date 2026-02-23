"""FastAPI 认证依赖注入

提供可复用的依赖函数，用于端点级别的认证和授权。
"""

from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from src.auth.security import decode_token
from src.storage.database import get_db_manager
from src.storage.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def _get_user_by_id(user_id: int) -> Optional[User]:
    db = get_db_manager()
    with db.get_session() as session:
        user = session.get(User, user_id)
        if user:
            session.expunge(user)
        return user


async def get_current_user(token: Optional[str] = Depends(oauth2_scheme)) -> User:
    """必须登录才能访问的端点使用此依赖"""
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证凭据",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Token 类型无效")
        user_id = int(payload["sub"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token 已过期")
    except (jwt.InvalidTokenError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Token 无效")

    user = _get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="用户不存在")
    return user


async def get_current_user_optional(
    token: Optional[str] = Depends(oauth2_scheme),
) -> Optional[User]:
    """可选认证：有 token 则解析用户，无 token 返回 None"""
    if token is None:
        return None
    try:
        return await get_current_user(token)
    except HTTPException:
        return None


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """要求管理员权限"""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user
