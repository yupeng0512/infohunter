"""内容分析器

使用 Knot AG-UI 对采集的内容进行 AI 分析。
支持单条分析和批量分析。
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from loguru import logger

from src.config import settings
from .agui_client import AGUIClient, create_content_agent, create_trend_agent


# Prompt 模板目录
PROMPTS_DIR = Path(__file__).parent.parent.parent / "config" / "prompts"


def _load_prompt(name: str) -> str:
    """加载 Prompt 模板"""
    path = PROMPTS_DIR / f"{name}.txt"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


class ContentAnalyzer:
    """内容分析器

    使用独立的 Agent 客户端进行内容分析和趋势分析。
    """

    def __init__(
        self,
        content_client: Optional[AGUIClient] = None,
        trend_client: Optional[AGUIClient] = None,
    ):
        self.client = content_client  # 内容分析 Agent
        self.trend_client = trend_client  # 趋势分析 Agent
        self._initialized = False

    def _ensure_client(self) -> bool:
        """确保内容分析 Agent 可用"""
        if self._initialized:
            return self.client is not None
        self._initialized = True

        if self.client:
            return True

        if not settings.knot_enabled:
            logger.info("ContentAnalyzer disabled: KNOT_ENABLED=false")
            return False

        try:
            self.client = create_content_agent()
            if not self.client:
                logger.warning("ContentAnalyzer disabled: content agent not configured")
                return False
            self.trend_client = create_trend_agent()
            logger.info("ContentAnalyzer initialized with dedicated agents")
            return True
        except Exception as e:
            logger.error(f"Failed to init ContentAnalyzer: {e}")
            return False

    async def analyze_content(
        self,
        content: str,
        source: str = "twitter",
        title: Optional[str] = None,
        author: Optional[str] = None,
        metrics: Optional[dict] = None,
        transcript: Optional[str] = None,
        analysis_focus: Optional[str] = None,
    ) -> dict[str, Any]:
        """分析单条内容

        Returns:
            {
                "status": "success" | "error" | "disabled",
                "analysis": {...},
                "raw_content": "...",
                "error": None,
                "analyzed_at": "...",
            }
        """
        result = {
            "status": "disabled",
            "analysis": None,
            "raw_content": "",
            "error": None,
            "analyzed_at": datetime.now().isoformat(),
        }

        if not self._ensure_client():
            result["error"] = "Analyzer not configured"
            return result

        try:
            prompt = self._build_content_prompt(
                content=content,
                source=source,
                title=title,
                author=author,
                metrics=metrics,
                transcript=transcript,
                analysis_focus=analysis_focus,
            )

            response = await self.client.chat(message=prompt, temperature=0.3)

            if response["error"]:
                result["status"] = "error"
                result["error"] = response["error"]
                return result

            raw_content = response["content"]
            result["raw_content"] = raw_content

            analysis = AGUIClient.extract_json(raw_content)
            if analysis:
                result["status"] = "success"
                result["analysis"] = analysis
            else:
                result["status"] = "success"
                result["analysis"] = {"raw_response": raw_content}

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            logger.error(f"Content analysis failed: {e}")

        return result

    async def analyze_batch(
        self,
        items: list[dict],
        focus: str = "trend_summary",
    ) -> dict[str, Any]:
        """批量分析内容 (用于日报/周报)

        使用趋势分析 Agent（如果配置了），否则回退到内容分析 Agent。
        """
        result = {
            "status": "disabled",
            "analysis": None,
            "raw_content": "",
            "error": None,
            "analyzed_at": datetime.now().isoformat(),
        }

        if not self._ensure_client():
            result["error"] = "Analyzer not configured"
            return result

        if not items:
            result["error"] = "No items to analyze"
            return result

        # 优先使用趋势分析 Agent
        agent = self.trend_client or self.client

        try:
            prompt = self._build_batch_prompt(items, focus)
            response = await agent.chat(message=prompt, temperature=0.3)

            if response["error"]:
                result["status"] = "error"
                result["error"] = response["error"]
                return result

            raw_content = response["content"]
            result["raw_content"] = raw_content

            # 保存原始 Agent 输出用于调试
            try:
                debug_path = Path(__file__).parent.parent.parent / "logs" / "debug_raw.txt"
                debug_path.parent.mkdir(parents=True, exist_ok=True)
                debug_path.write_text(raw_content, encoding="utf-8")
            except Exception:
                pass

            analysis = AGUIClient.extract_json(raw_content)
            if analysis:
                result["status"] = "success"
                result["analysis"] = analysis
                logger.info("Batch extract_json succeeded on first attempt")
            else:
                logger.warning(
                    f"Batch extract_json failed, raw_len={len(raw_content)}, "
                    f"starts={repr(raw_content[:80])}, "
                    f"ends={repr(raw_content[-50:])}"
                )
                cleaned = self._clean_ai_output(raw_content)
                analysis = AGUIClient.extract_json(cleaned)
                if analysis:
                    result["status"] = "success"
                    result["analysis"] = analysis
                    logger.info("Batch extract_json succeeded after cleanup")
                else:
                    logger.warning(
                        f"Batch extract_json still failed after cleanup, "
                        f"cleaned_len={len(cleaned)}, "
                        f"starts={repr(cleaned[:80])}"
                    )
                    result["status"] = "success"
                    result["analysis"] = {"raw_response": raw_content}

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            logger.error(f"Batch analysis failed: {e}", exc_info=True)

        return result

    @staticmethod
    def _clean_ai_output(text: str) -> str:
        """清理 AI 输出中的干扰内容，尝试修复常见 JSON 格式问题"""
        import re

        text = re.sub(r'<thinking>[\s\S]*?</thinking>', '', text)
        text = re.sub(r'```json\s*', '', text)
        text = re.sub(r'```\s*', '', text)

        # 将中日韩引号替换为单引号，避免破坏 JSON 结构
        text = (
            text
            .replace('\u300c', "'").replace('\u300d', "'")
            .replace('\u201c', "'").replace('\u201d', "'")
            .replace('\u2018', "'").replace('\u2019', "'")
        )

        brace_pos = text.find('{')
        if brace_pos > 0:
            text = text[brace_pos:]
        last_brace = text.rfind('}')
        if last_brace > 0:
            text = text[:last_brace + 1]
        text = text.strip()

        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)

        try:
            json.loads(text)
            return text
        except json.JSONDecodeError:
            pass

        try:
            json.loads(text, strict=False)
            return text
        except json.JSONDecodeError:
            pass

        def _fix_json_value(match: re.Match) -> str:
            value = match.group(0)
            return value.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')

        try:
            text = re.sub(
                r'(?<=: ")((?:[^"\\]|\\.)*)(?=")', _fix_json_value, text
            )
        except Exception as e:
            logger.debug(f"JSON value fix regex failed: {e}")

        return text

    def _build_content_prompt(
        self,
        content: str,
        source: str,
        title: Optional[str] = None,
        author: Optional[str] = None,
        metrics: Optional[dict] = None,
        transcript: Optional[str] = None,
        analysis_focus: Optional[str] = None,
    ) -> str:
        """构建内容分析 Prompt"""
        focus_map = {
            "opportunity": "侧重发现机会：识别潜在创业方向、技术应用或投资机会",
            "frontier": "侧重前沿动态：提炼关键技术演进方向和行业变化",
            "knowledge": "侧重知识拓展：指出值得深入学习的知识点和技术原理",
            "comprehensive": "综合分析：机会发现 + 前沿动态 + 知识拓展",
        }
        focus_text = focus_map.get(analysis_focus or "", focus_map["comprehensive"])

        custom_prompt = _load_prompt("content_analysis")
        if custom_prompt:
            return custom_prompt.format(
                content=content,
                source=source,
                title=title or "",
                author=author or "",
                metrics=json.dumps(metrics or {}, ensure_ascii=False),
                transcript=transcript or "",
                analysis_focus=focus_text,
            )

        # 默认 Prompt
        input_data = {
            "source": source,
            "content": content,
        }
        if title:
            input_data["title"] = title
        if author:
            input_data["author"] = author
        if metrics:
            input_data["metrics"] = metrics
        if transcript:
            input_data["transcript"] = transcript[:3000]

        return f"""请分析以下社交媒体内容，提取关键信息：

```json
{json.dumps(input_data, ensure_ascii=False, indent=2)}
```

请输出 JSON 格式的分析报告，包含以下字段：
- summary: 一句话摘要 (中文)
- key_points: 核心观点列表 (中文, 最多5条)
- sentiment: 情感倾向 (positive/negative/neutral)
- topics: 涉及的话题标签列表
- importance: 重要性评分 (1-10)
- recommendation: 是否值得关注的建议 (中文)

请直接输出 JSON，不要添加额外说明。"""

    def _build_batch_prompt(self, items: list[dict], focus: str) -> str:
        """构建批量分析 Prompt"""
        period = "24小时" if "daily" in focus else "7天" if "weekly" in focus else "一段时间"

        custom_prompt = _load_prompt("trend_analysis")
        if custom_prompt:
            return custom_prompt.format(
                items=json.dumps(items, ensure_ascii=False, indent=2),
                focus=focus,
                count=len(items),
                period=period,
            )

        # 默认 Prompt
        simplified = []
        for item in items[:30]:
            entry = {"content": item.get("content", "")[:200]}
            if item.get("title"):
                entry["title"] = item["title"]
            if item.get("source"):
                entry["source"] = item["source"]
            simplified.append(entry)

        return f"""请综合分析以下 {len(simplified)} 条社交媒体内容，生成趋势报告：

```json
{json.dumps(simplified, ensure_ascii=False, indent=2)}
```

分析重点: {focus}

请输出 JSON 格式的趋势报告，包含：
- overall_summary: 整体趋势总结 (中文, 2-3句话)
- hot_topics: 热门话题列表 (每个包含 topic, heat, description)
- key_insights: 关键洞察列表 (中文, 最多5条)
- emerging_trends: 新兴趋势 (中文)
- recommendation: 建议关注的方向 (中文)

请直接输出 JSON。"""


# 全局实例
_content_analyzer: Optional[ContentAnalyzer] = None


def get_content_analyzer() -> ContentAnalyzer:
    global _content_analyzer
    if _content_analyzer is None:
        _content_analyzer = ContentAnalyzer()
    return _content_analyzer
