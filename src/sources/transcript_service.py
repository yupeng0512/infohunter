"""YouTube 字幕提取服务

双层架构:
  主: youtube-transcript-api (开源、免费、无需 API Key)
  备: ScrapeCreators API     (付费、仅在主方案失败时使用)
"""

import asyncio
from typing import Optional

from loguru import logger

try:
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import (
        NoTranscriptFound,
        TranscriptsDisabled,
        VideoUnavailable,
    )

    _YTA_AVAILABLE = True
    _yta_client = YouTubeTranscriptApi()
except ImportError:
    _YTA_AVAILABLE = False
    _yta_client = None
    logger.warning(
        "youtube-transcript-api not installed, "
        "TranscriptService will rely on ScrapeCreators fallback only"
    )


class TranscriptService:
    """YouTube 字幕提取服务（主: youtube-transcript-api, 备: ScrapeCreators）"""

    DEFAULT_LANGUAGES = ["en", "zh-Hans", "zh-Hant", "zh", "ja", "ko"]

    def __init__(self, fallback_client=None):
        """
        Args:
            fallback_client: ScrapeCreators YouTubeTranscriptClient 实例（可选）
        """
        self.fallback_client = fallback_client
        if _YTA_AVAILABLE:
            logger.info("TranscriptService ready (primary: youtube-transcript-api)")
        elif fallback_client:
            logger.info("TranscriptService ready (ScrapeCreators only)")
        else:
            logger.warning("TranscriptService: no transcript provider available")

    async def get_transcript(
        self,
        video_id: str,
        languages: Optional[list[str]] = None,
    ) -> Optional[str]:
        """获取 YouTube 视频字幕

        优先使用免费的 youtube-transcript-api，失败后回退到 ScrapeCreators。

        Args:
            video_id: YouTube 视频 ID
            languages: 偏好语言列表，按优先级排序

        Returns:
            字幕纯文本，或 None
        """
        langs = languages or self.DEFAULT_LANGUAGES

        # --- 主方案: youtube-transcript-api ---
        if _YTA_AVAILABLE:
            transcript = await self._fetch_via_yta(video_id, langs)
            if transcript:
                return transcript

        # --- 备方案: ScrapeCreators ---
        if self.fallback_client:
            transcript = await self._fetch_via_scrapecreators(video_id)
            if transcript:
                return transcript

        return None

    async def _fetch_via_yta(
        self, video_id: str, languages: list[str]
    ) -> Optional[str]:
        """使用 youtube-transcript-api 获取字幕（同步库，需 run_in_executor）"""
        loop = asyncio.get_running_loop()
        try:
            text = await loop.run_in_executor(
                None, self._yta_sync_fetch, video_id, languages
            )
            if text:
                logger.debug(
                    f"[TranscriptService] yta success: {video_id} "
                    f"({len(text)} chars)"
                )
                return text
        except Exception as e:
            logger.debug(f"[TranscriptService] yta failed for {video_id}: {e}")
        return None

    @staticmethod
    def _yta_sync_fetch(video_id: str, languages: list[str]) -> Optional[str]:
        """同步调用 youtube-transcript-api (v1.x: 实例方法 + FetchedTranscript)"""
        try:
            result = _yta_client.fetch(video_id, languages=languages)
            text = " ".join(s.text for s in result.snippets if s.text)
            return text.strip() if text.strip() else None
        except (NoTranscriptFound, TranscriptsDisabled, VideoUnavailable):
            raise
        except Exception:
            # 尝试获取任何可用字幕
            transcript_list = _yta_client.list(video_id)
            for t in transcript_list:
                fetched = t.fetch()
                text = " ".join(s.text for s in fetched.snippets if s.text)
                if text.strip():
                    return text.strip()
        return None

    async def _fetch_via_scrapecreators(self, video_id: str) -> Optional[str]:
        """使用 ScrapeCreators 获取字幕（付费 fallback）"""
        try:
            transcript = await self.fallback_client.get_transcript(video_id)
            if transcript:
                logger.debug(
                    f"[TranscriptService] scrapecreators fallback success: "
                    f"{video_id} ({len(transcript)} chars)"
                )
                return transcript
        except Exception as e:
            logger.debug(
                f"[TranscriptService] scrapecreators fallback failed for "
                f"{video_id}: {e}"
            )
        return None
