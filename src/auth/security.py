"""JWT Token 生成与密码哈希工具"""

import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from loguru import logger

from src.config import settings

_jwt_secret: str = settings.jwt_secret_key
if not _jwt_secret:
    _jwt_secret = secrets.token_hex(32)
    logger.warning(
        "JWT_SECRET_KEY 未配置，已自动生成临时密钥。"
        "重启后所有 token 将失效。请在 .env 中配置 JWT_SECRET_KEY。"
    )


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(user_id: int, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.jwt_access_token_expire_minutes
    )
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "exp": expire,
    }
    return jwt.encode(payload, _jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.jwt_refresh_token_expire_days
    )
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "exp": expire,
    }
    return jwt.encode(payload, _jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    """解码并验证 JWT token，过期或无效时抛出异常"""
    return jwt.decode(
        token,
        _jwt_secret,
        algorithms=[settings.jwt_algorithm],
    )
