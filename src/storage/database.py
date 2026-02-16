"""数据库管理模块

InfoHunter 多源数据存储管理器。
"""

from datetime import datetime
from functools import lru_cache
from typing import Optional

from loguru import logger
from sqlalchemy import create_engine, func, select, and_
from sqlalchemy.orm import Session, sessionmaker

from src.config import settings
from .models import Base, Content, FetchLog, Subscription, SystemConfig


class DatabaseManager:
    """数据库管理器"""

    def __init__(self, database_url: Optional[str] = None):
        self.database_url = database_url or settings.database_url
        self.engine = create_engine(
            self.database_url,
            pool_size=5,
            max_overflow=10,
            pool_recycle=3600,
            echo=False,
        )
        self.SessionLocal = sessionmaker(
            bind=self.engine,
            autocommit=False,
            autoflush=False,
        )

    def init_db(self) -> None:
        """初始化数据库表"""
        logger.info("初始化数据库表...")
        Base.metadata.create_all(bind=self.engine)
        logger.info("数据库表初始化完成")

    def get_session(self) -> Session:
        """获取数据库会话"""
        return self.SessionLocal()

    # ===== 订阅管理 =====

    def create_subscription(self, data: dict) -> Subscription:
        """创建订阅"""
        with self.get_session() as session:
            sub = Subscription(**data)
            session.add(sub)
            session.commit()
            session.refresh(sub)
            logger.info(f"创建订阅: {sub.name} ({sub.source}/{sub.type}: {sub.target})")
            return self._detach(sub, Subscription)

    def get_subscription(self, sub_id: int) -> Optional[Subscription]:
        """获取单个订阅"""
        with self.get_session() as session:
            sub = session.get(Subscription, sub_id)
            if sub:
                return self._detach(sub, Subscription)
            return None

    def list_subscriptions(
        self,
        source: Optional[str] = None,
        status: str = "active",
    ) -> list[Subscription]:
        """列出订阅"""
        with self.get_session() as session:
            query = select(Subscription)
            if source:
                query = query.where(Subscription.source == source)
            if status:
                query = query.where(Subscription.status == status)
            query = query.order_by(Subscription.created_at.desc())
            subs = session.execute(query).scalars().all()
            return [self._detach(s, Subscription) for s in subs]

    def update_subscription(self, sub_id: int, data: dict) -> Optional[Subscription]:
        """更新订阅"""
        with self.get_session() as session:
            sub = session.get(Subscription, sub_id)
            if not sub:
                return None
            for key, value in data.items():
                if hasattr(sub, key):
                    setattr(sub, key, value)
            session.commit()
            session.refresh(sub)
            return self._detach(sub, Subscription)

    def delete_subscription(self, sub_id: int) -> bool:
        """软删除订阅"""
        with self.get_session() as session:
            sub = session.get(Subscription, sub_id)
            if not sub:
                return False
            sub.status = "deleted"
            session.commit()
            return True

    def get_due_subscriptions(self) -> list[Subscription]:
        """获取需要采集的订阅 (已到采集间隔)"""
        now = datetime.now()
        with self.get_session() as session:
            subs = session.execute(
                select(Subscription).where(
                    Subscription.status == "active"
                )
            ).scalars().all()

            due = []
            for sub in subs:
                if sub.last_fetched_at is None:
                    due.append(self._detach(sub, Subscription))
                else:
                    elapsed = (now - sub.last_fetched_at).total_seconds()
                    if elapsed >= sub.fetch_interval:
                        due.append(self._detach(sub, Subscription))
            return due

    def update_subscription_fetched(self, sub_id: int) -> None:
        """更新订阅的最后采集时间"""
        with self.get_session() as session:
            sub = session.get(Subscription, sub_id)
            if sub:
                sub.last_fetched_at = datetime.now()
                session.commit()

    # ===== 内容管理 =====

    def save_content(self, data: dict) -> tuple[Content, bool]:
        """保存内容 (upsert)

        Returns:
            (Content, is_new)
        """
        with self.get_session() as session:
            existing = session.execute(
                select(Content).where(
                    and_(
                        Content.content_id == data.get("content_id"),
                        Content.source == data.get("source"),
                    )
                )
            ).scalar_one_or_none()

            if existing:
                for key, value in data.items():
                    if key not in ("content_id", "source") and hasattr(existing, key):
                        setattr(existing, key, value)
                session.commit()
                session.refresh(existing)
                return self._detach(existing, Content), False
            else:
                content = Content(**data)
                session.add(content)
                session.commit()
                session.refresh(content)
                return self._detach(content, Content), True

    def save_contents_batch(self, items: list[dict]) -> tuple[int, int]:
        """批量保存内容

        Returns:
            (new_count, updated_count)
        """
        new_count = 0
        updated_count = 0

        with self.get_session() as session:
            for data in items:
                existing = session.execute(
                    select(Content).where(
                        and_(
                            Content.content_id == data.get("content_id"),
                            Content.source == data.get("source"),
                        )
                    )
                ).scalar_one_or_none()

                if existing:
                    for key, value in data.items():
                        if key not in ("content_id", "source") and hasattr(existing, key):
                            setattr(existing, key, value)
                    updated_count += 1
                else:
                    content = Content(**data)
                    session.add(content)
                    new_count += 1

            session.commit()

        logger.info(f"批量保存完成: 新增 {new_count}, 更新 {updated_count}")
        return new_count, updated_count

    def get_unnotified_contents(
        self,
        limit: int = 50,
        min_quality: Optional[float] = None,
    ) -> list[Content]:
        """获取未通知的内容"""
        with self.get_session() as session:
            query = (
                select(Content)
                .where(Content.notified == False)
                .order_by(Content.posted_at.desc())
                .limit(limit)
            )
            if min_quality is not None:
                query = query.where(Content.quality_score >= min_quality)
            contents = session.execute(query).scalars().all()
            return [self._detach(c, Content) for c in contents]

    def get_unanalyzed_contents(self, limit: int = 50) -> list[Content]:
        """获取未进行 AI 分析的内容"""
        with self.get_session() as session:
            contents = session.execute(
                select(Content)
                .where(Content.ai_analyzed_at == None)
                .order_by(Content.posted_at.desc())
                .limit(limit)
            ).scalars().all()
            return [self._detach(c, Content) for c in contents]

    def update_ai_analysis(self, content_id: int, analysis: dict) -> None:
        """更新内容的 AI 分析结果"""
        with self.get_session() as session:
            session.execute(
                Content.__table__.update()
                .where(Content.id == content_id)
                .values(ai_analysis=analysis, ai_analyzed_at=datetime.now())
            )
            session.commit()

    def update_scores(
        self,
        content_id: int,
        relevance_score: Optional[float] = None,
        quality_score: Optional[float] = None,
    ) -> None:
        """更新内容评分"""
        values = {}
        if relevance_score is not None:
            values["relevance_score"] = relevance_score
        if quality_score is not None:
            values["quality_score"] = quality_score
        if not values:
            return

        with self.get_session() as session:
            session.execute(
                Content.__table__.update()
                .where(Content.id == content_id)
                .values(**values)
            )
            session.commit()

    def mark_contents_notified(self, content_ids: list[int]) -> None:
        """标记内容为已通知"""
        with self.get_session() as session:
            session.execute(
                Content.__table__.update()
                .where(Content.id.in_(content_ids))
                .values(notified=True, notified_at=datetime.now())
            )
            session.commit()

    def get_contents_by_subscription(
        self,
        subscription_id: int,
        limit: int = 50,
        since: Optional[datetime] = None,
    ) -> list[Content]:
        """获取订阅下的内容"""
        with self.get_session() as session:
            query = (
                select(Content)
                .where(Content.subscription_id == subscription_id)
                .order_by(Content.posted_at.desc())
                .limit(limit)
            )
            if since:
                query = query.where(Content.posted_at >= since)
            contents = session.execute(query).scalars().all()
            return [self._detach(c, Content) for c in contents]

    def get_contents_for_report(
        self,
        since: datetime,
        source: Optional[str] = None,
        limit: int = 200,
    ) -> list[Content]:
        """获取报告所需的内容"""
        with self.get_session() as session:
            query = (
                select(Content)
                .where(Content.posted_at >= since)
                .order_by(Content.quality_score.desc().nullslast())
                .limit(limit)
            )
            if source:
                query = query.where(Content.source == source)
            contents = session.execute(query).scalars().all()
            return [self._detach(c, Content) for c in contents]

    def content_exists(self, content_id: str, source: str) -> bool:
        """检查内容是否已存在"""
        with self.get_session() as session:
            result = session.execute(
                select(Content.id).where(
                    and_(
                        Content.content_id == content_id,
                        Content.source == source,
                    )
                )
            ).scalar_one_or_none()
            return result is not None

    # ===== 采集日志 =====

    def log_fetch(
        self,
        subscription_id: Optional[int],
        source: str,
        status: str,
        total_fetched: int = 0,
        new_items: int = 0,
        filtered_items: int = 0,
        error_message: Optional[str] = None,
        started_at: Optional[datetime] = None,
    ) -> FetchLog:
        """记录采集日志"""
        with self.get_session() as session:
            now = datetime.now()
            duration = None
            if started_at:
                duration = (now - started_at).total_seconds()

            log = FetchLog(
                subscription_id=subscription_id,
                source=source,
                status=status,
                total_fetched=total_fetched,
                new_items=new_items,
                filtered_items=filtered_items,
                error_message=error_message,
                started_at=started_at or now,
                finished_at=now,
                duration_seconds=duration,
            )
            session.add(log)
            session.commit()
            session.refresh(log)
            return log

    # ===== 统计 =====

    def get_content_count(self, source: Optional[str] = None) -> int:
        """获取内容总数"""
        with self.get_session() as session:
            query = select(func.count(Content.id))
            if source:
                query = query.where(Content.source == source)
            return session.execute(query).scalar() or 0

    def get_subscription_count(self, status: str = "active") -> int:
        """获取订阅数"""
        with self.get_session() as session:
            query = select(func.count(Subscription.id))
            if status:
                query = query.where(Subscription.status == status)
            return session.execute(query).scalar() or 0

    # ===== 辅助方法 =====

    def _detach(self, obj, model_class):
        """分离 ORM 对象，使其可在会话外使用"""
        data = {}
        for column in model_class.__table__.columns:
            data[column.name] = getattr(obj, column.name)
        detached = model_class(**data)
        return detached


@lru_cache
def get_db_manager() -> DatabaseManager:
    """获取数据库管理器单例"""
    return DatabaseManager()
