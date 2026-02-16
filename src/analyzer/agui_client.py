"""AG-UI 协议客户端

通过 AG-UI 协议调用 Knot 平台上的智能体。
复用自 truthsocial-trump-monitor，适配 InfoHunter 多源架构。
"""

import json
import re
from datetime import datetime
from typing import Any, AsyncGenerator, Optional

import httpx
from loguru import logger

from src.config import settings


class AGUIClient:
    """AG-UI 协议客户端

    通过 AG-UI 协议调用 AI Agent 平台。
    默认使用 KNOT_API_BASE_URL 环境变量配置 API 地址。
    """

    API_URL_TEMPLATE = "{base_url}/apigw/api/v1/agents/agui/{agent_id}"
    DEFAULT_TIMEOUT = 120

    def __init__(
        self,
        agent_id: Optional[str] = None,
        api_token: Optional[str] = None,
        agent_token: Optional[str] = None,
        username: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.agent_id = agent_id or settings.knot_agent_id
        self.api_token = api_token or settings.knot_api_token
        self.agent_token = agent_token or settings.knot_agent_token
        self.username = username or settings.knot_username
        self.model = model or settings.knot_model
        self.base_url = base_url or settings.knot_api_base_url
        self.timeout = timeout

        if not self.agent_id:
            raise ValueError("Agent ID is required (KNOT_AGENT_ID)")
        if not self.api_token and not self.agent_token:
            raise ValueError("Either KNOT_API_TOKEN or KNOT_AGENT_TOKEN is required")
        if self.agent_token and not self.username:
            raise ValueError("KNOT_USERNAME is required when using Agent Token")

        self.api_url = self.API_URL_TEMPLATE.format(
            base_url=self.base_url.rstrip("/"), agent_id=self.agent_id
        )
        logger.info(
            f"AGUIClient initialized: agent_id={self.agent_id}, "
            f"model={self.model}, auth={'api_token' if self.api_token else 'agent_token'}"
        )

    def _build_headers(self) -> dict[str, str]:
        if self.api_token:
            return {
                "x-knot-api-token": self.api_token,
                "Content-Type": "application/json",
            }
        return {
            "x-knot-token": self.agent_token,
            "X-Username": self.username,
            "Content-Type": "application/json",
        }

    def _build_request_body(
        self,
        message: str,
        conversation_id: str = "",
        stream: bool = True,
        temperature: float = 0.5,
    ) -> dict[str, Any]:
        return {
            "input": {
                "message": message,
                "conversation_id": conversation_id,
                "model": self.model,
                "stream": stream,
                "temperature": temperature,
                "chat_extra": {
                    "attached_images": [],
                    "extra_headers": {},
                },
            }
        }

    async def chat(
        self,
        message: str,
        conversation_id: str = "",
        temperature: float = 0.5,
    ) -> dict[str, Any]:
        """发送消息并获取完整响应"""
        headers = self._build_headers()
        body = self._build_request_body(
            message=message,
            conversation_id=conversation_id,
            stream=True,
            temperature=temperature,
        )

        result = {
            "content": "",
            "conversation_id": "",
            "message_id": "",
            "thinking": "",
            "tool_calls": [],
            "token_usage": None,
            "error": None,
        }

        content_parts = []
        thinking_parts = []

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST", self.api_url, json=body, headers=headers
                ) as response:
                    if response.status_code != 200:
                        error_text = await response.aread()
                        result["error"] = f"HTTP {response.status_code}: {error_text.decode()}"
                        logger.error(f"AGUI request failed: {result['error']}")
                        return result

                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        chunk_str = line.lstrip("data:").strip()
                        if chunk_str == "[DONE]":
                            break
                        try:
                            msg = json.loads(chunk_str)
                        except json.JSONDecodeError:
                            continue
                        if "type" not in msg:
                            continue

                        msg_type = msg["type"]
                        raw_event = msg.get("rawEvent", {})

                        if "conversation_id" in raw_event:
                            result["conversation_id"] = raw_event["conversation_id"]
                        if "message_id" in raw_event:
                            result["message_id"] = raw_event["message_id"]

                        if msg_type == "TEXT_MESSAGE_CONTENT":
                            content_parts.append(raw_event.get("content", ""))
                        elif msg_type == "THINKING_TEXT_MESSAGE_CONTENT":
                            thinking_parts.append(raw_event.get("content", ""))
                        elif msg_type == "TOOL_CALL_START":
                            result["tool_calls"].append({
                                "name": raw_event.get("name"),
                                "status": "started",
                            })
                        elif msg_type == "TOOL_CALL_RESULT":
                            if result["tool_calls"]:
                                result["tool_calls"][-1]["status"] = "completed"
                                result["tool_calls"][-1]["result"] = raw_event.get("result")
                        elif msg_type == "STEP_FINISHED":
                            if "token_usage" in raw_event:
                                result["token_usage"] = raw_event["token_usage"]
                        elif msg_type == "RUN_ERROR":
                            tip_option = raw_event.get("tip_option", {})
                            result["error"] = tip_option.get("content", "Unknown error")

            result["content"] = "".join(content_parts)
            result["thinking"] = "".join(thinking_parts)

        except httpx.TimeoutException:
            result["error"] = f"Request timeout after {self.timeout}s"
            logger.error(result["error"])
        except Exception as e:
            result["error"] = str(e)
            logger.error(f"AGUI request exception: {e}")

        return result

    @staticmethod
    def extract_json(text: str) -> Optional[dict]:
        """从文本中提取 JSON"""
        if not text:
            return None

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        json_pattern = r'```(?:json)?\s*([\s\S]*?)\s*```'
        matches = re.findall(json_pattern, text)
        for match in matches:
            try:
                return json.loads(match)
            except json.JSONDecodeError:
                continue

        brace_pattern = r'\{[\s\S]*\}'
        matches = re.findall(brace_pattern, text)
        for match in matches:
            try:
                return json.loads(match)
            except json.JSONDecodeError:
                continue

        return None
