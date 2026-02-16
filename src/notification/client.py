"""飞书通知客户端

支持飞书流程 Webhook 触发器和传统群机器人 Webhook。
默认使用纯文本推送，简化消息格式。
"""

import base64
import hashlib
import hmac
import time
from typing import Optional

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import settings


class FeishuClient:
    """飞书通知客户端

    支持两种 Webhook 类型：
    1. 流程 Webhook (Bot Builder / Flow): 纯文本推送
    2. 传统群机器人 Webhook: 支持卡片消息
    """

    TYPE_BOT_WEBHOOK = "bot_webhook"
    TYPE_FLOW_WEBHOOK = "flow_webhook"

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
        logger.info(f"Feishu client initialized: type={self.webhook_type}")

    def _detect_webhook_type(self, url: str) -> str:
        """自动检测 Webhook 类型"""
        if (
            "botbuilder.feishu.cn" in url
            or "trigger-webhook" in url
            or "/flow/api/" in url
        ):
            return self.TYPE_FLOW_WEBHOOK
        return self.TYPE_BOT_WEBHOOK

    def _gen_sign(self, timestamp: str) -> str:
        """生成签名（仅传统群机器人需要）"""
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
        """发送消息到飞书"""
        # 传统群机器人需要签名
        if self.secret and self.webhook_type == self.TYPE_BOT_WEBHOOK:
            timestamp = str(int(time.time()))
            payload["timestamp"] = timestamp
            payload["sign"] = self._gen_sign(timestamp)

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    self.webhook_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                if response.status_code != 200:
                    logger.error(
                        f"Feishu send failed: HTTP {response.status_code}, "
                        f"body={response.text[:200]}"
                    )
                    return False

                result = response.json()
                # 兼容两种响应格式
                if result.get("code") == 0 or result.get("StatusCode") == 0:
                    return True

                # 流程 Webhook 可能返回其他格式
                if "msg" in result and result.get("msg") == "success":
                    return True

                logger.error(f"Feishu send failed: {result}")
                return False

        except Exception as e:
            logger.error(f"Feishu send exception: {e}")
            raise

    async def send_text(self, text: str) -> bool:
        """发送纯文本消息

        统一使用简化格式:
        {
            "message_type": "text",
            "content": {
                "text": "内容"
            }
        }
        """
        if len(text) > self.max_length:
            text = text[: self.max_length - 3] + "..."

        payload = {
            "message_type": "text",
            "content": {
                "text": text,
            },
        }
        return await self._send(payload)

    async def send_markdown_card(
        self,
        title: str,
        content: str,
        header_color: str = "blue",
    ) -> bool:
        """发送消息（自动适配 Webhook 类型）

        - 流程 Webhook: 转为纯文本发送
        - 传统群机器人: 发送 Markdown 卡片
        """
        if self.webhook_type == self.TYPE_FLOW_WEBHOOK:
            # 流程 Webhook 统一使用纯文本
            text = f"{'=' * 30}\n{title}\n{'=' * 30}\n\n{content}"
            return await self.send_text(text)

        # 传统群机器人使用卡片格式
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

    async def send_alert(
        self, title: str, content: str, level: str = "info"
    ) -> bool:
        """发送告警消息"""
        level_prefix = {"info": "ℹ️", "warning": "⚠️", "error": "❌"}.get(
            level, "ℹ️"
        )
        if self.webhook_type == self.TYPE_FLOW_WEBHOOK:
            text = f"{level_prefix} {title}\n\n{content}"
            return await self.send_text(text)

        color_map = {"info": "blue", "warning": "orange", "error": "red"}
        return await self.send_markdown_card(
            f"{level_prefix} {title}", content, color_map.get(level, "blue")
        )
