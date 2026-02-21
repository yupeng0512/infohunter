"""订阅管理器

管理订阅的 CRUD 操作和调度逻辑。
"""

from typing import Optional

from loguru import logger

from src.storage.database import DatabaseManager, get_db_manager
from src.storage.models import Subscription


class SubscriptionManager:
    """订阅管理器"""

    def __init__(self, db: Optional[DatabaseManager] = None):
        self.db = db or get_db_manager()

    def create(self, data: dict) -> Subscription:
        """创建订阅"""
        sub = self.db.create_subscription(data)
        logger.info(f"订阅已创建: [{sub.source}] {sub.name} -> {sub.target}")
        return sub

    def get(self, sub_id: int) -> Optional[Subscription]:
        """获取订阅"""
        return self.db.get_subscription(sub_id)

    def list_all(
        self,
        source: Optional[str] = None,
        sub_type: Optional[str] = None,
        status: str = "active",
    ) -> list[Subscription]:
        """列出订阅"""
        return self.db.list_subscriptions(source=source, sub_type=sub_type, status=status)

    def update(self, sub_id: int, data: dict) -> Optional[Subscription]:
        """更新订阅"""
        filtered = {k: v for k, v in data.items() if v is not None}
        if not filtered:
            return self.get(sub_id)
        sub = self.db.update_subscription(sub_id, filtered)
        if sub:
            logger.info(f"订阅已更新: [{sub.source}] {sub.name}")
        return sub

    def delete(self, sub_id: int) -> bool:
        """删除订阅 (软删除)"""
        result = self.db.delete_subscription(sub_id)
        if result:
            logger.info(f"订阅已删除: id={sub_id}")
        return result

    def get_due_subscriptions(self) -> list[Subscription]:
        """获取需要采集的订阅"""
        return self.db.get_due_subscriptions()

    def mark_fetched(self, sub_id: int) -> None:
        """标记订阅已采集"""
        self.db.update_subscription_fetched(sub_id)
