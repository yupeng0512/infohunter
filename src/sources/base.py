"""数据源抽象基类

所有数据源客户端必须继承此基类。
"""

from abc import ABC, abstractmethod
from typing import Any, Optional

from loguru import logger


class SourceClient(ABC):
    """数据源客户端抽象基类"""

    source_name: str = "unknown"

    @abstractmethod
    async def search(
        self,
        query: str,
        limit: int = 20,
        **kwargs,
    ) -> list[dict[str, Any]]:
        """搜索内容

        Args:
            query: 搜索关键词
            limit: 返回数量限制
            **kwargs: 额外参数

        Returns:
            标准化的内容列表，每个元素包含:
            - content_id: 平台原始 ID
            - source: 数据源标识
            - author: 作者名称
            - author_id: 作者 ID
            - title: 标题 (可选)
            - content: 正文内容
            - url: 原文链接
            - metrics: 互动指标 dict
            - posted_at: 发布时间 (datetime)
            - raw_data: 原始数据
        """
        ...

    @abstractmethod
    async def get_author_content(
        self,
        author_id: str,
        limit: int = 20,
        **kwargs,
    ) -> list[dict[str, Any]]:
        """获取作者/频道的内容

        Args:
            author_id: 作者/频道 ID
            limit: 返回数量限制

        Returns:
            标准化的内容列表
        """
        ...

    async def get_detail(
        self,
        content_id: str,
        **kwargs,
    ) -> Optional[dict[str, Any]]:
        """获取单条内容详情

        Args:
            content_id: 内容 ID

        Returns:
            标准化的内容字典，或 None
        """
        return None

    async def get_transcript(
        self,
        content_id: str,
        **kwargs,
    ) -> Optional[str]:
        """获取内容的文字稿/字幕

        Args:
            content_id: 内容 ID

        Returns:
            文字稿文本，或 None
        """
        return None

    def _log_request(self, method: str, **params) -> None:
        """记录 API 请求日志"""
        logger.debug(f"[{self.source_name}] {method}: {params}")

    def _log_error(self, method: str, error: Exception) -> None:
        """记录错误日志"""
        logger.error(f"[{self.source_name}] {method} failed: {error}")
