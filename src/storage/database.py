"""数据库管理模块

InfoHunter 多源数据存储管理器。
"""

from datetime import datetime, timedelta
from functools import lru_cache
from typing import Optional
from zoneinfo import ZoneInfo

from loguru import logger
from sqlalchemy import create_engine, func, select, and_
from sqlalchemy.orm import Session, sessionmaker

from src.config import settings
from .models import Base, Content, CreditUsage, FetchLog, Subscription, SystemConfig

_LOCAL_TZ = ZoneInfo(settings.timezone)


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
        self._run_migrations()
        logger.info("数据库表初始化完成")

    def _run_migrations(self) -> None:
        """执行必要的数据库迁移 (幂等)"""
        from sqlalchemy import text, inspect

        inspector = inspect(self.engine)
        if "contents" not in inspector.get_table_names():
            return

        columns = {c["name"]: c for c in inspector.get_columns("contents")}
        content_id_col = columns.get("content_id")
        if content_id_col and getattr(content_id_col["type"], "length", 0) < 512:
            try:
                with self.engine.begin() as conn:
                    conn.execute(text(
                        "ALTER TABLE contents MODIFY COLUMN content_id VARCHAR(512) NOT NULL"
                    ))
                logger.info("迁移: contents.content_id 扩展到 VARCHAR(512)")
            except Exception as e:
                logger.warning(f"迁移 content_id 列失败 (可能已完成): {e}")

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
        sub_type: Optional[str] = None,
        status: str = "active",
    ) -> list[Subscription]:
        """列出订阅"""
        with self.get_session() as session:
            query = select(Subscription)
            if source:
                query = query.where(Subscription.source == source)
            if sub_type:
                query = query.where(Subscription.type == sub_type)
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
        clean = self._clean_content_data(data)
        with self.get_session() as session:
            existing = session.execute(
                select(Content).where(
                    and_(
                        Content.content_id == clean.get("content_id"),
                        Content.source == clean.get("source"),
                    )
                )
            ).scalar_one_or_none()

            if existing:
                for key, value in clean.items():
                    if key not in ("content_id", "source"):
                        setattr(existing, key, value)
                session.commit()
                session.refresh(existing)
                return self._detach(existing, Content), False
            else:
                content = Content(**clean)
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
                clean = self._clean_content_data(data)
                existing = session.execute(
                    select(Content).where(
                        and_(
                            Content.content_id == clean.get("content_id"),
                            Content.source == clean.get("source"),
                        )
                    )
                ).scalar_one_or_none()

                if existing:
                    for key, value in clean.items():
                        if key not in ("content_id", "source"):
                            setattr(existing, key, value)
                    updated_count += 1
                else:
                    content = Content(**clean)
                    session.add(content)
                    new_count += 1

            session.commit()

        logger.info(f"批量保存完成: 新增 {new_count}, 更新 {updated_count}")
        return new_count, updated_count

    def get_unnotified_contents(
        self,
        limit: int = 50,
        min_quality: Optional[float] = None,
        require_analyzed: bool = True,
    ) -> list[Content]:
        """获取未通知的内容（默认要求已通过 AI 分析）"""
        with self.get_session() as session:
            query = (
                select(Content)
                .where(Content.notified == False)
                .order_by(Content.posted_at.desc())
                .limit(limit)
            )
            if require_analyzed:
                query = query.where(Content.ai_analyzed_at != None)
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

    def get_unanalyzed_contents_prioritized(self, limit: int = 20) -> list[Content]:
        """按优先级获取未分析内容

        优先级策略：
        1. 有订阅关联的（订阅流）> 无订阅关联的（探索流）
        2. 发布时间越新越优先
        3. 同等条件下按入库时间排序
        """
        from sqlalchemy import case

        with self.get_session() as session:
            source_priority = case(
                (Content.subscription_id != None, 0),
                else_=1,
            )
            contents = session.execute(
                select(Content)
                .where(Content.ai_analyzed_at == None)
                .order_by(
                    source_priority.asc(),
                    Content.posted_at.desc().nulls_last(),
                    Content.created_at.desc(),
                )
                .limit(limit)
            ).scalars().all()
            return [self._detach(c, Content) for c in contents]

    def get_analyzed_contents_in_window(
        self,
        window_start: datetime,
        window_end: datetime,
        notified: Optional[bool] = None,
        min_importance: Optional[int] = None,
        limit: int = 50,
    ) -> list[Content]:
        """获取时间窗口内已分析的内容

        Args:
            window_start: 窗口开始时间
            window_end: 窗口结束时间
            notified: None=不过滤, True=已推送, False=未推送
            min_importance: 最低 importance 分值过滤
            limit: 返回条数上限
        """
        with self.get_session() as session:
            query = (
                select(Content)
                .where(
                    and_(
                        Content.ai_analyzed_at != None,
                        Content.ai_analyzed_at >= window_start,
                        Content.ai_analyzed_at < window_end,
                    )
                )
            )
            if notified is not None:
                query = query.where(Content.notified == notified)

            query = query.order_by(
                Content.quality_score.desc().nulls_last(),
                Content.posted_at.desc(),
            ).limit(limit)

            contents = session.execute(query).scalars().all()
            return [self._detach(c, Content) for c in contents]

    def get_unnotified_analyzed_since(
        self,
        since: datetime,
        limit: int = 50,
    ) -> list[Content]:
        """获取指定时间之后已分析但未推送的内容"""
        with self.get_session() as session:
            contents = session.execute(
                select(Content)
                .where(
                    and_(
                        Content.ai_analyzed_at != None,
                        Content.notified == False,
                        Content.ai_analyzed_at >= since,
                    )
                )
                .order_by(Content.quality_score.desc().nulls_last())
                .limit(limit)
            ).scalars().all()
            return [self._detach(c, Content) for c in contents]

    def get_last_notify_time(self) -> Optional[datetime]:
        """获取最近一次推送时间"""
        with self.get_session() as session:
            result = session.execute(
                select(func.max(Content.notified_at))
                .where(Content.notified == True)
            ).scalar()
            return result

    def update_ai_analysis(
        self,
        content_id: int,
        analysis: dict,
        importance: Optional[int] = None,
    ) -> None:
        """更新内容的 AI 分析结果，同时写入 importance 映射的 quality_score"""
        values: dict = {
            "ai_analysis": analysis,
            "ai_analyzed_at": datetime.now(),
        }
        if importance is not None:
            values["quality_score"] = importance / 10.0
        with self.get_session() as session:
            session.execute(
                Content.__table__.update()
                .where(Content.id == content_id)
                .values(**values)
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
                .order_by(Content.quality_score.desc())
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

    def get_subscription_count(self, status: str = "active", source: Optional[str] = None) -> int:
        """获取订阅数"""
        with self.get_session() as session:
            query = select(func.count(Subscription.id))
            if status:
                query = query.where(Subscription.status == status)
            if source:
                query = query.where(Subscription.source == source)
            return session.execute(query).scalar() or 0

    # ===== 系统配置 =====

    def list_system_configs(self) -> list[SystemConfig]:
        """列出所有系统配置"""
        with self.get_session() as session:
            configs = session.execute(
                select(SystemConfig).order_by(SystemConfig.config_key)
            ).scalars().all()
            return [self._detach(c, SystemConfig) for c in configs]

    def get_system_config(self, key: str) -> Optional[SystemConfig]:
        """获取单个系统配置"""
        with self.get_session() as session:
            config = session.execute(
                select(SystemConfig).where(SystemConfig.config_key == key)
            ).scalar_one_or_none()
            if config:
                return self._detach(config, SystemConfig)
            return None

    def set_system_config(
        self, key: str, value: dict, description: Optional[str] = None
    ) -> SystemConfig:
        """设置系统配置 (upsert)"""
        with self.get_session() as session:
            existing = session.execute(
                select(SystemConfig).where(SystemConfig.config_key == key)
            ).scalar_one_or_none()

            if existing:
                existing.config_value = value
                if description is not None:
                    existing.description = description
                session.commit()
                session.refresh(existing)
                return self._detach(existing, SystemConfig)
            else:
                config = SystemConfig(
                    config_key=key,
                    config_value=value,
                    description=description,
                )
                session.add(config)
                session.commit()
                session.refresh(config)
                return self._detach(config, SystemConfig)

    def delete_system_config(self, key: str) -> bool:
        """删除系统配置"""
        with self.get_session() as session:
            config = session.execute(
                select(SystemConfig).where(SystemConfig.config_key == key)
            ).scalar_one_or_none()
            if not config:
                return False
            session.delete(config)
            session.commit()
            return True

    # ===== Credit 消耗追踪 =====

    def log_credit_usage(
        self,
        source: str,
        operation: str,
        credits: int,
        detail: Optional[str] = None,
        context: str = "explore",
    ) -> CreditUsage:
        """记录一次 API credit 消耗"""
        with self.get_session() as session:
            record = CreditUsage(
                source=source,
                operation=operation,
                credits=credits,
                detail=detail[:255] if detail and len(detail) > 255 else detail,
                context=context,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return record

    def get_credit_usage_today(self, source: Optional[str] = None) -> int:
        """获取今日 credit 消耗总量"""
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        with self.get_session() as session:
            query = select(func.coalesce(func.sum(CreditUsage.credits), 0)).where(
                CreditUsage.created_at >= today
            )
            if source:
                query = query.where(CreditUsage.source == source)
            return session.execute(query).scalar() or 0

    def get_credit_usage_range(
        self,
        since: datetime,
        until: Optional[datetime] = None,
        source: Optional[str] = None,
    ) -> list[dict]:
        """获取时间范围内按日分组的 credit 消耗统计"""
        with self.get_session() as session:
            date_col = func.date(CreditUsage.created_at).label("date")
            query = (
                select(
                    date_col,
                    CreditUsage.operation,
                    CreditUsage.context,
                    func.sum(CreditUsage.credits).label("total_credits"),
                    func.count(CreditUsage.id).label("call_count"),
                )
                .where(CreditUsage.created_at >= since)
                .group_by(date_col, CreditUsage.operation, CreditUsage.context)
                .order_by(date_col.desc())
            )
            if until:
                query = query.where(CreditUsage.created_at < until)
            if source:
                query = query.where(CreditUsage.source == source)
            rows = session.execute(query).all()
            return [
                {
                    "date": str(r.date),
                    "operation": r.operation,
                    "context": r.context,
                    "total_credits": r.total_credits,
                    "call_count": r.call_count,
                }
                for r in rows
            ]

    def get_credit_daily_totals(
        self, days: int = 30, source: Optional[str] = None
    ) -> list[dict]:
        """获取最近 N 天每日 credit 总消耗"""
        since = datetime.now() - timedelta(days=days)
        with self.get_session() as session:
            date_col = func.date(CreditUsage.created_at).label("date")
            query = (
                select(
                    date_col,
                    func.sum(CreditUsage.credits).label("total_credits"),
                    func.count(CreditUsage.id).label("call_count"),
                )
                .where(CreditUsage.created_at >= since)
                .group_by(date_col)
                .order_by(date_col.asc())
            )
            if source:
                query = query.where(CreditUsage.source == source)
            rows = session.execute(query).all()
            return [
                {
                    "date": str(r.date),
                    "total_credits": r.total_credits,
                    "call_count": r.call_count,
                }
                for r in rows
            ]

    def get_credit_usage_by_operation(
        self, since: datetime, source: Optional[str] = None
    ) -> list[dict]:
        """获取指定时间后按操作类型分组的 credit 消耗"""
        with self.get_session() as session:
            query = (
                select(
                    CreditUsage.operation,
                    CreditUsage.context,
                    func.sum(CreditUsage.credits).label("total_credits"),
                    func.count(CreditUsage.id).label("call_count"),
                )
                .where(CreditUsage.created_at >= since)
                .group_by(CreditUsage.operation, CreditUsage.context)
                .order_by(func.sum(CreditUsage.credits).desc())
            )
            if source:
                query = query.where(CreditUsage.source == source)
            rows = session.execute(query).all()
            return [
                {
                    "operation": r.operation,
                    "context": r.context,
                    "total_credits": r.total_credits,
                    "call_count": r.call_count,
                }
                for r in rows
            ]

    def get_credit_recent_records(
        self, limit: int = 50, source: Optional[str] = None
    ) -> list[CreditUsage]:
        """获取最近的 credit 消耗记录"""
        with self.get_session() as session:
            query = (
                select(CreditUsage)
                .order_by(CreditUsage.created_at.desc())
                .limit(limit)
            )
            if source:
                query = query.where(CreditUsage.source == source)
            records = session.execute(query).scalars().all()
            return [self._detach(r, CreditUsage) for r in records]

    # ===== 额外统计 =====

    def get_content_count_since(self, since: datetime) -> int:
        """获取指定时间之后的内容数"""
        with self.get_session() as session:
            return session.execute(
                select(func.count(Content.id)).where(Content.created_at >= since)
            ).scalar() or 0

    def get_unnotified_count(self) -> int:
        """获取未通知内容数"""
        with self.get_session() as session:
            return session.execute(
                select(func.count(Content.id)).where(Content.notified == False)
            ).scalar() or 0

    def get_fetch_logs(
        self,
        limit: int = 50,
        subscription_id: Optional[int] = None,
    ) -> list[FetchLog]:
        """获取采集日志"""
        with self.get_session() as session:
            query = (
                select(FetchLog)
                .order_by(FetchLog.started_at.desc())
                .limit(limit)
            )
            if subscription_id is not None:
                query = query.where(FetchLog.subscription_id == subscription_id)
            logs = session.execute(query).scalars().all()
            return [self._detach(log, FetchLog) for log in logs]

    # ===== 辅助方法 =====

    @staticmethod
    def _clean_content_data(data: dict) -> dict:
        """过滤 Content 模型不支持的字段，防止 SQLAlchemy TypeError。
        同时将带时区的 posted_at 统一转为本地时区 naive datetime，
        确保与 datetime.now() 可比。
        """
        valid_columns = {c.name for c in Content.__table__.columns}
        clean = {k: v for k, v in data.items() if k in valid_columns}

        posted = clean.get("posted_at")
        if isinstance(posted, datetime) and posted.tzinfo is not None:
            clean["posted_at"] = posted.astimezone(_LOCAL_TZ).replace(tzinfo=None)

        return clean

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
