"""飞书通知客户端

支持传统群机器人 Webhook 和 Bot Builder Webhook 触发器。
适配 InfoHunter 多源内容推送。
"""

import base64
import hashlib
import hmac
import time
from datetime import datetime
from typing import Optional

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import settings


class FeishuClient:
    """飞书机器人客户端"""

    TYPE_BOT_WEBHOOK = "bot_webhook"
    TYPE_BOT_BUILDER = "bot_builder"

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        secret: Optional[str] = None,
        max_length: int = 30000,
    ):
        self.webhook_url = webhook_url or settings.feishu_webhook_url
        self.secret = secret or settings.feishu_secret
        self.max_length = max_length

        if not self.webhook_url:
            raise ValueError("Feishu webhook URL is required")

        self.webhook_type = self._detect_webhook_type(self.webhook_url)
        logger.info(f"Feishu client initialized: {self.webhook_type}")

    def _detect_webhook_type(self, url: str) -> str:
        if "botbuilder.feishu.cn" in url or "trigger-webhook" in url or "/flow/api/" in url:
            return self.TYPE_BOT_BUILDER
        return self.TYPE_BOT_WEBHOOK

    def _gen_sign(self, timestamp: str) -> str:
        if not self.secret:
            return ""
        string_to_sign = f"{timestamp}\n{self.secret}"
        hmac_code = hmac.new(
            string_to_sign.encode("utf-8"), digestmod=hashlib.sha256
        ).digest()
        return base64.b64encode(hmac_code).decode("utf-8")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def _send(self, payload: dict) -> bool:
        if self.secret and self.webhook_type == self.TYPE_BOT_WEBHOOK:
            timestamp = str(int(time.time()))
            payload["timestamp"] = timestamp
            payload["sign"] = self._gen_sign(timestamp)

        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            if response.status_code != 200:
                logger.error(f"Feishu send failed: {response.status_code}")
                return False
            result = response.json()
            if result.get("code") != 0 and result.get("StatusCode") != 0:
                logger.error(f"Feishu send failed: {result}")
                return False
            return True

    async def send_text(self, text: str) -> bool:
        """发送文本消息"""
        if len(text) > self.max_length:
            text = text[: self.max_length - 3] + "..."
        return await self._send({"msg_type": "text", "content": {"text": text}})

    async def send_markdown_card(
        self,
        title: str,
        content: str,
        header_color: str = "blue",
    ) -> bool:
        """发送 Markdown 卡片消息"""
        if self.webhook_type == self.TYPE_BOT_BUILDER:
            text = f"{title}\n\n{content}"
            return await self.send_text(text)

        payload = {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {"tag": "plain_text", "content": title},
                    "template": header_color,
                },
                "elements": [{"tag": "markdown", "content": content}],
            },
        }
        return await self._send(payload)

    async def send_alert(self, title: str, content: str, level: str = "info") -> bool:
        color_map = {"info": "blue", "warning": "orange", "error": "red"}
        return await self.send_markdown_card(title, content, color_map.get(level, "blue"))
