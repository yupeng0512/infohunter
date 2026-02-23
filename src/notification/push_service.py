"""Expo Push Notification Service

通过 Expo Push Service 向 App 用户发送推送通知。
设备注册信息存储在 MySQL 的 device_tokens 表中。
支持用户级推送（关联 user_id）和广播推送。
"""

from datetime import datetime
from typing import Optional

from loguru import logger
from pydantic import BaseModel

try:
    from exponent_server_sdk import (
        DeviceNotRegisteredError,
        PushClient,
        PushMessage,
        PushServerError,
    )
    HAS_EXPO_SDK = True
except ImportError:
    HAS_EXPO_SDK = False
    logger.warning("exponent_server_sdk 未安装，推送功能不可用")


class DeviceRegistration(BaseModel):
    device_id: str
    platform: str
    push_token: str
    app_version: Optional[str] = None
    user_id: Optional[int] = None


class DeviceResponse(BaseModel):
    id: int
    device_id: str
    platform: str
    push_token: str
    app_version: Optional[str]
    user_id: Optional[int]
    created_at: datetime
    updated_at: datetime


class PushService:
    """Expo Push Notification Service

    通过 Expo Push Service API 发送推送，
    支持广播和用户级定向推送。
    """

    def __init__(self, db_manager):
        self.db = db_manager
        self._ensure_table()

    def _ensure_table(self):
        try:
            from sqlalchemy import text
            with self.db.engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS device_tokens (
                        id INTEGER PRIMARY KEY AUTO_INCREMENT,
                        device_id VARCHAR(255) NOT NULL UNIQUE,
                        platform VARCHAR(32) NOT NULL,
                        push_token TEXT NOT NULL,
                        app_version VARCHAR(32),
                        user_id INT NULL,
                        is_active BOOLEAN DEFAULT TRUE,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        INDEX idx_dt_user (user_id),
                        INDEX idx_dt_active (is_active)
                    )
                """))
                conn.commit()

                cols = {r[0] for r in conn.execute(text(
                    "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_NAME = 'device_tokens' AND TABLE_SCHEMA = DATABASE()"
                )).fetchall()}
                if "user_id" not in cols:
                    conn.execute(text("ALTER TABLE device_tokens ADD COLUMN user_id INT NULL"))
                    conn.commit()
                    logger.info("迁移: device_tokens 新增 user_id 列")
        except Exception as e:
            logger.warning(f"device_tokens 表初始化失败: {e}")

    def register_device(self, reg: DeviceRegistration) -> dict:
        try:
            from sqlalchemy import text
            with self.db.engine.connect() as conn:
                existing = conn.execute(
                    text("SELECT id FROM device_tokens WHERE device_id = :did"),
                    {"did": reg.device_id},
                ).fetchone()

                if existing:
                    conn.execute(
                        text("""
                            UPDATE device_tokens
                            SET push_token = :token, platform = :platform,
                                app_version = :version, user_id = :uid, is_active = TRUE
                            WHERE device_id = :did
                        """),
                        {
                            "token": reg.push_token,
                            "platform": reg.platform,
                            "version": reg.app_version,
                            "uid": reg.user_id,
                            "did": reg.device_id,
                        },
                    )
                    conn.commit()
                    logger.info(f"设备更新: {reg.device_id} (user={reg.user_id})")
                    return {"status": "updated", "device_id": reg.device_id}
                else:
                    conn.execute(
                        text("""
                            INSERT INTO device_tokens (device_id, platform, push_token, app_version, user_id)
                            VALUES (:did, :platform, :token, :version, :uid)
                        """),
                        {
                            "did": reg.device_id,
                            "platform": reg.platform,
                            "token": reg.push_token,
                            "version": reg.app_version,
                            "uid": reg.user_id,
                        },
                    )
                    conn.commit()
                    logger.info(f"设备注册: {reg.device_id} (user={reg.user_id})")
                    return {"status": "registered", "device_id": reg.device_id}
        except Exception as e:
            logger.error(f"设备注册失败: {e}")
            raise

    def unregister_device(self, device_id: str) -> dict:
        try:
            from sqlalchemy import text
            with self.db.engine.connect() as conn:
                conn.execute(
                    text("UPDATE device_tokens SET is_active = FALSE WHERE device_id = :did"),
                    {"did": device_id},
                )
                conn.commit()
            return {"status": "unregistered", "device_id": device_id}
        except Exception as e:
            logger.error(f"设备注销失败: {e}")
            raise

    def get_active_tokens(self, platform: Optional[str] = None, user_id: Optional[int] = None) -> list[dict]:
        try:
            from sqlalchemy import text
            query = "SELECT device_id, platform, push_token, user_id FROM device_tokens WHERE is_active = TRUE"
            params: dict = {}
            if platform:
                query += " AND platform = :platform"
                params["platform"] = platform
            if user_id is not None:
                query += " AND user_id = :uid"
                params["uid"] = user_id

            with self.db.engine.connect() as conn:
                rows = conn.execute(text(query), params).fetchall()
            return [
                {"device_id": r[0], "platform": r[1], "push_token": r[2], "user_id": r[3]}
                for r in rows
            ]
        except Exception as e:
            logger.error(f"获取活跃设备失败: {e}")
            return []

    async def send_push(
        self,
        title: str,
        body: str,
        data: Optional[dict] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """发送推送通知

        Args:
            title: 通知标题
            body: 通知正文
            data: 附加数据（点击通知时传递给 App）
            user_id: 目标用户 ID（None 表示广播给所有设备）
        """
        tokens = self.get_active_tokens(user_id=user_id)
        if not tokens:
            return {"status": "no_devices", "sent": 0}

        if not HAS_EXPO_SDK:
            logger.warning(f"Expo SDK 未安装，跳过推送 ({len(tokens)} 个设备)")
            return {"status": "sdk_unavailable", "target_devices": len(tokens)}

        expo_tokens = [
            t["push_token"] for t in tokens
            if t["push_token"].startswith("ExponentPushToken[")
        ]

        if not expo_tokens:
            return {"status": "no_expo_tokens", "sent": 0}

        messages = [
            PushMessage(
                to=token,
                title=title,
                body=body,
                data=data or {},
                sound="default",
                badge=1,
            )
            for token in expo_tokens
        ]

        sent = 0
        failed = 0
        try:
            push_client = PushClient()
            responses = push_client.publish_multiple(messages)

            for i, response in enumerate(responses):
                try:
                    response.validate_response()
                    sent += 1
                except DeviceNotRegisteredError:
                    self._deactivate_token(expo_tokens[i])
                    failed += 1
                except Exception as e:
                    logger.warning(f"推送响应异常: {e}")
                    failed += 1

        except PushServerError as e:
            logger.error(f"Expo Push Server 错误: {e}")
            return {"status": "server_error", "error": str(e)}
        except Exception as e:
            logger.error(f"推送发送失败: {e}")
            return {"status": "error", "error": str(e)}

        logger.info(f"推送完成: sent={sent}, failed={failed}, target={'user=' + str(user_id) if user_id else 'broadcast'}")
        return {"status": "ok", "sent": sent, "failed": failed}

    def _deactivate_token(self, push_token: str):
        try:
            from sqlalchemy import text
            with self.db.engine.connect() as conn:
                conn.execute(
                    text("UPDATE device_tokens SET is_active = FALSE WHERE push_token = :token"),
                    {"token": push_token},
                )
                conn.commit()
            logger.info(f"设备 token 已停用（未注册）: {push_token[:30]}...")
        except Exception as e:
            logger.warning(f"停用 token 失败: {e}")

    async def push_content_to_user(
        self,
        user_id: int,
        content_title: str,
        content_summary: str,
        content_id: int,
        source: str,
    ) -> dict:
        """推送单条内容通知给指定用户"""
        source_labels = {"twitter": "Twitter", "youtube": "YouTube", "blog": "Blog"}
        title = f"[{source_labels.get(source, source)}] {content_title or '新内容'}"
        body = content_summary[:100] if content_summary else "查看详情"
        data = {"content_id": content_id, "source": source, "type": "content"}
        return await self.send_push(title=title, body=body, data=data, user_id=user_id)

    async def push_daily_digest(self, user_id: Optional[int] = None, count: int = 0) -> dict:
        """推送日报摘要通知"""
        title = "InfoHunter 今日速报"
        body = f"今日新增 {count} 条内容，点击查看详情"
        data = {"type": "daily_digest"}
        return await self.send_push(title=title, body=body, data=data, user_id=user_id)
