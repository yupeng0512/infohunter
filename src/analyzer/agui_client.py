"""AG-UI 协议客户端

通过 AG-UI 协议调用 Knot 平台上的智能体。
支持多 Agent 独立配置（各自端点 + API Key）。
"""

import json
import re
from typing import Any, AsyncGenerator, Optional

import httpx
from loguru import logger

from src.config import settings


class AGUIClient:
    """AG-UI 协议客户端

    每个 Agent 有独立的 agent_id 和 api_key。
    API URL 格式: {base_url}/apigw/api/v1/agents/agui/{agent_id}
    """

    DEFAULT_TIMEOUT = 120

    def __init__(
        self,
        agent_id: str,
        api_key: str,
        username: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.agent_id = agent_id
        self.api_key = api_key
        self.username = username or settings.knot_username
        self.model = model or settings.knot_model
        self.base_url = (base_url or settings.knot_api_base_url).rstrip("/")
        self.timeout = timeout

        if not self.agent_id:
            raise ValueError("Agent ID is required")
        if not self.api_key:
            raise ValueError("Agent API Key is required")

        # 判断 token 类型：knot_ 开头为智能体 token，否则为用户个人 token
        self._is_agent_token = self.api_key.startswith("knot_")

        self.api_url = f"{self.base_url}/apigw/api/v1/agents/agui/{self.agent_id}"
        logger.info(
            f"AGUIClient initialized: agent_id={self.agent_id[:8]}..., "
            f"model={self.model}, auth={'agent_token' if self._is_agent_token else 'api_token'}"
        )

    def _build_headers(self) -> dict[str, str]:
        """构建请求头

        智能体 token (knot_ 开头): x-knot-token + X-Username
        用户个人 token: x-knot-api-token
        """
        headers = {"Content-Type": "application/json"}

        if self._is_agent_token:
            headers["x-knot-token"] = self.api_key
            if self.username:
                headers["X-Username"] = self.username
        else:
            headers["x-knot-api-token"] = self.api_key

        return headers

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
                        chunk_str = line.removeprefix("data:").strip()
                        if not chunk_str:
                            continue
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
    def _normalize_quotes(text: str) -> str:
        """将中日韩引号替换为 JSON 安全字符（单引号），避免破坏 JSON 结构"""
        return (
            text
            .replace('\u300c', "'").replace('\u300d', "'")   # 「」
            .replace('\u201c', "'").replace('\u201d', "'")   # ""
            .replace('\u2018', "'").replace('\u2019', "'")   # ''
        )

    @staticmethod
    def _fix_unescaped_quotes(text: str) -> str:
        """修复 JSON 字符串值内部未转义的双引号

        AI 生成的 JSON 中常出现类似 "...等待"成熟方案"..." 这样的内容。
        通过字符级状态机判断哪些双引号属于 JSON 结构，哪些在字符串值内需要转义。
        """
        result = []
        in_string = False
        i = 0
        n = len(text)
        while i < n:
            c = text[i]
            if not in_string:
                result.append(c)
                if c == '"':
                    in_string = True
            else:
                if c == '\\' and i + 1 < n:
                    result.append(c)
                    result.append(text[i + 1])
                    i += 2
                    continue
                if c == '"':
                    rest = text[i + 1:].lstrip()
                    if rest and rest[0] in ',}]:':
                        result.append(c)
                        in_string = False
                    elif not rest or rest[0] == '\n':
                        # End of line or end of text — likely end of string
                        j = i + 1
                        while j < n and text[j] in ' \t\r\n':
                            j += 1
                        if j >= n or text[j] in '"}]':
                            result.append(c)
                            in_string = False
                        else:
                            result.append('\\"')
                    else:
                        result.append('\\"')
                else:
                    result.append(c)
            i += 1
        return ''.join(result)

    @staticmethod
    def extract_json(text: str) -> Optional[dict]:
        """从文本中提取 JSON，多层容错"""
        if not text:
            return None

        text_stripped = text.strip().lstrip('\ufeff')

        # 1. 直接解析
        try:
            result = json.loads(text_stripped)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

        # 2. 放宽控制字符限制
        try:
            result = json.loads(text_stripped, strict=False)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

        # 3. 从 markdown 代码块提取
        json_pattern = r'```(?:json)?\s*([\s\S]*?)\s*```'
        matches = re.findall(json_pattern, text)
        for match in matches:
            try:
                result = json.loads(match, strict=False)
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                continue

        # 4. 贪婪提取最外层 {} + 中文引号归一化
        brace_start = text.find('{')
        brace_end = text.rfind('}')
        if brace_start >= 0 and brace_end > brace_start:
            candidate = AGUIClient._normalize_quotes(text[brace_start:brace_end + 1])
            try:
                result = json.loads(candidate, strict=False)
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError as e:
                logger.debug(
                    f"extract_json brace extraction failed: {e}, "
                    f"len={len(candidate)}, near_error={repr(candidate[max(0,e.pos-30):e.pos+30])}"
                )

        # 5. 清理控制字符 + 修复尾部逗号后重试
        if brace_start >= 0 and brace_end > brace_start:
            candidate = AGUIClient._normalize_quotes(text[brace_start:brace_end + 1])
            candidate = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', candidate)
            candidate = re.sub(r',\s*([\]}])', r'\1', candidate)
            try:
                result = json.loads(candidate, strict=False)
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass

        # 6. 终极回退：修复字符串值中未转义的双引号
        if brace_start >= 0 and brace_end > brace_start:
            candidate = AGUIClient._normalize_quotes(text[brace_start:brace_end + 1])
            candidate = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', candidate)
            candidate = re.sub(r',\s*([\]}])', r'\1', candidate)
            candidate = AGUIClient._fix_unescaped_quotes(candidate)
            try:
                result = json.loads(candidate, strict=False)
                if isinstance(result, dict):
                    logger.info("extract_json succeeded via unescaped-quote fix")
                    return result
            except json.JSONDecodeError as e:
                logger.debug(f"extract_json final fallback failed: {e}")

        return None


def create_content_agent() -> Optional[AGUIClient]:
    """创建内容分析 Agent 客户端"""
    agent_id = settings.knot_content_agent_id or settings.knot_agent_id
    api_key = settings.knot_content_agent_key or settings.knot_api_token
    if not agent_id or not api_key:
        return None
    return AGUIClient(agent_id=agent_id, api_key=api_key)


def create_trend_agent() -> Optional[AGUIClient]:
    """创建趋势分析 Agent 客户端"""
    agent_id = settings.knot_trend_agent_id
    api_key = settings.knot_trend_agent_key
    if not agent_id or not api_key:
        return create_content_agent()  # fallback
    return AGUIClient(agent_id=agent_id, api_key=api_key)


def create_recommend_agent() -> Optional[AGUIClient]:
    """创建博主评估 Agent 客户端"""
    agent_id = settings.knot_recommend_agent_id
    api_key = settings.knot_recommend_agent_key
    if not agent_id or not api_key:
        return create_content_agent()  # fallback
    return AGUIClient(agent_id=agent_id, api_key=api_key)
