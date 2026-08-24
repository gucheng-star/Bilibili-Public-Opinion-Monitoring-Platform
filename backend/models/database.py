"""数据库模型"""

from datetime import datetime
import os
import sqlite3
from pathlib import Path

from sqlalchemy import Column, Integer, String, Text, Float, DateTime, ForeignKey, UniqueConstraint, create_engine, event
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker

from services.runtime_paths import database_path


DB_PATH = str(database_path())
DB_URL = f"sqlite:///{DB_PATH}"
engine = create_engine(DB_URL, echo=False, connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _configure_sqlite_connection(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


class Analysis(Base):
    __tablename__ = "analyses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    bv = Column(String(20), nullable=False, index=True)
    avid = Column(Integer, nullable=False)
    video_title = Column(String(500))
    video_cover = Column(String(500))
    video_play = Column(Integer)
    status = Column(String(20), default="pending")
    mode = Column(String(10), default="nlp")
    total_comments = Column(Integer, default=0)
    processed_comments = Column(Integer, default=0)
    error_msg = Column(Text)
    created_at = Column(DateTime, default=datetime.now)

    comments = relationship("Comment", back_populates="analysis", cascade="all, delete-orphan")
    sentiment = relationship("SentimentResult", back_populates="analysis", uselist=False, cascade="all, delete-orphan")
    summaries = relationship("AISummary", back_populates="analysis", cascade="all, delete-orphan")
    group_items = relationship("AnalysisGroupItem", back_populates="analysis", passive_deletes=True)


class Comment(Base):
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    analysis_id = Column(Integer, ForeignKey("analyses.id"), nullable=False, index=True)
    rpid = Column(Integer, nullable=False)
    root_rpid = Column(Integer)
    parent_rpid = Column(Integer)
    username = Column(String(100))
    gender = Column(String(10))
    ip_location = Column(String(50))
    content = Column(Text)
    likes = Column(Integer, default=0)
    sentiment_label = Column(String(10))
    sentiment_score = Column(Float)
    sentiment_llm_label = Column(String(20), default="")
    sentiment_llm_style = Column(String(20), default="plain")
    post_time = Column(DateTime, nullable=False)

    analysis = relationship("Analysis", back_populates="comments")


class SentimentResult(Base):
    __tablename__ = "sentiment_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    analysis_id = Column(Integer, ForeignKey("analyses.id"), nullable=False, unique=True)
    positive_count = Column(Integer, default=0)
    negative_count = Column(Integer, default=0)
    neutral_count = Column(Integer, default=0)
    llm_neutral = Column(Integer, default=0)
    llm_joy = Column(Integer, default=0)
    llm_support = Column(Integer, default=0)
    llm_anger = Column(Integer, default=0)
    llm_sadness = Column(Integer, default=0)
    llm_surprise = Column(Integer, default=0)
    llm_fear = Column(Integer, default=0)
    llm_disgust = Column(Integer, default=0)
    llm_anticipation = Column(Integer, default=0)
    llm_concern = Column(Integer, default=0)
    llm_trust = Column(Integer, default=0)
    llm_sarcasm = Column(Integer, default=0)

    analysis = relationship("Analysis", back_populates="sentiment")


class AISummary(Base):
    __tablename__ = "ai_summaries"
    __table_args__ = (
        UniqueConstraint("analysis_id", "filter_hash", name="uq_ai_summary_analysis_filter"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    analysis_id = Column(Integer, ForeignKey("analyses.id"), nullable=False, index=True)
    filter_json = Column(Text, nullable=False)
    filter_hash = Column(String(64), nullable=False)
    input_hash = Column(String(64), nullable=False)
    summary_text = Column(Text, nullable=False)
    provider = Column(String(30), nullable=False)
    model = Column(String(100), nullable=False)
    matched_count = Column(Integer, default=0)
    sampled_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    analysis = relationship("Analysis", back_populates="summaries")


class AnalysisGroup(Base):
    """A user-curated event which references completed single-video analyses."""

    __tablename__ = "analysis_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    items = relationship(
        "AnalysisGroupItem", back_populates="group", cascade="all, delete-orphan",
        passive_deletes=True, order_by="AnalysisGroupItem.position",
    )
    summaries = relationship(
        "AnalysisGroupSummary", back_populates="group", cascade="all, delete-orphan",
        passive_deletes=True,
    )


class AnalysisGroupItem(Base):
    """Stable ordered membership for an event; comments remain owned by Analysis."""

    __tablename__ = "analysis_group_items"
    __table_args__ = (
        UniqueConstraint("group_id", "analysis_id", name="uq_analysis_group_item"),
        UniqueConstraint("group_id", "position", name="uq_analysis_group_item_position"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(
        Integer, ForeignKey("analysis_groups.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    analysis_id = Column(
        Integer, ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    position = Column(Integer, nullable=False)
    added_at = Column(DateTime, default=datetime.now, nullable=False)

    group = relationship("AnalysisGroup", back_populates="items")
    analysis = relationship("Analysis", back_populates="group_items")


class AnalysisGroupSummary(Base):
    """A separately scoped cached AI brief for an AnalysisGroup."""

    __tablename__ = "analysis_group_summaries"
    __table_args__ = (
        UniqueConstraint(
            "group_id", "analysis_mode", "filter_hash",
            name="uq_analysis_group_summary_scope",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(
        Integer, ForeignKey("analysis_groups.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    analysis_mode = Column(String(10), nullable=False)
    member_signature = Column(String(64), nullable=False)
    filter_json = Column(Text, nullable=False)
    filter_hash = Column(String(64), nullable=False)
    input_hash = Column(String(64), nullable=False)
    summary_text = Column(Text, nullable=False)
    provider = Column(String(30), nullable=False)
    model = Column(String(100), nullable=False)
    matched_count = Column(Integer, default=0)
    sampled_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    group = relationship("AnalysisGroup", back_populates="summaries")


def init_db():
    """Initialize and safely upgrade the local SQLite schema."""
    backup = None
    try:
        needs_backup = _schema_change_required(engine)
        if needs_backup:
            backup = _backup_database()
        Base.metadata.create_all(engine)
        _migrate(engine)
        _validate_schema(engine)
    except Exception as exc:
        if backup:
            try:
                engine.dispose()
                _restore_database(backup)
            except Exception as restore_exc:
                raise RuntimeError(f"数据库迁移失败且备份恢复失败：{restore_exc}") from exc
        raise RuntimeError(f"数据库迁移失败，未启动服务：{exc}") from exc
    _mark_interrupted_jobs()


def _backup_database(path: str | Path | None = None) -> Path | None:
    """Use SQLite's backup API so a WAL database is copied consistently."""
    source = Path(path or DB_PATH)
    if not source.exists():
        return None
    backup_dir = source.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    destination = backup_dir / f"{source.stem}-{stamp}.db"
    source_connection = sqlite3.connect(str(source))
    destination_connection = sqlite3.connect(str(destination))
    try:
        source_connection.backup(destination_connection)
    finally:
        destination_connection.close()
        source_connection.close()
    backups = sorted(backup_dir.glob(f"{source.stem}-*.db"), key=lambda item: item.stat().st_mtime, reverse=True)
    for stale in backups[3:]:
        stale.unlink(missing_ok=True)
    return destination


def _restore_database(backup: str | Path, path: str | Path | None = None) -> None:
    """Restore a backup atomically and discard any stale WAL sidecars."""
    source = Path(backup)
    destination = Path(path or DB_PATH)
    temporary = Path(str(destination) + ".restore.tmp")
    temporary.unlink(missing_ok=True)
    source_connection = sqlite3.connect(str(source))
    destination_connection = sqlite3.connect(str(temporary))
    try:
        source_connection.backup(destination_connection)
    finally:
        destination_connection.close()
        source_connection.close()
    os.replace(temporary, destination)
    for suffix in ("-wal", "-shm"):
        Path(str(destination) + suffix).unlink(missing_ok=True)


def _mark_interrupted_jobs() -> None:
    """A portable app may be closed by Windows before background work ends."""
    from sqlalchemy import text
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE analyses SET status = 'interrupted', "
                "error_msg = COALESCE(error_msg, '应用上次关闭时任务被中断') "
                "WHERE status IN ('pending', 'fetching', 'analyzing')"
            )
        )

def _pending_column_migrations(eng):
    from sqlalchemy import inspect
    inspector = inspect(eng)
    migrations = []

    if "analyses" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("analyses")}
        if "mode" not in cols:
            migrations.append(("analyses", "ALTER TABLE analyses ADD COLUMN mode VARCHAR(10) DEFAULT 'nlp'"))
        if "processed_comments" not in cols:
            migrations.append(("analyses", "ALTER TABLE analyses ADD COLUMN processed_comments INTEGER DEFAULT 0"))
    if "comments" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("comments")}
        if "sentiment_llm_label" not in cols:
            migrations.append(("comments", "ALTER TABLE comments ADD COLUMN sentiment_llm_label VARCHAR(20) DEFAULT ''"))
        if "sentiment_llm_style" not in cols:
            migrations.append(("comments", "ALTER TABLE comments ADD COLUMN sentiment_llm_style VARCHAR(20) DEFAULT 'plain'"))
        if "root_rpid" not in cols:
            migrations.append(("comments", "ALTER TABLE comments ADD COLUMN root_rpid INTEGER"))
        if "parent_rpid" not in cols:
            migrations.append(("comments", "ALTER TABLE comments ADD COLUMN parent_rpid INTEGER"))
    if "sentiment_results" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("sentiment_results")}
        llm_fields = [
            "llm_neutral", "llm_joy", "llm_support", "llm_anger", "llm_sadness", "llm_surprise",
            "llm_fear", "llm_disgust", "llm_anticipation", "llm_concern", "llm_trust", "llm_sarcasm",
        ]
        for field in llm_fields:
            if field not in cols:
                migrations.append(("sentiment_results", f"ALTER TABLE sentiment_results ADD COLUMN {field} INTEGER DEFAULT 0"))

    return migrations


def _schema_change_required(eng) -> bool:
    """Check before create_all so an existing database is backed up first."""
    source = Path(DB_PATH)
    if not source.exists():
        return False
    from sqlalchemy import inspect
    existing = set(inspect(eng).get_table_names())
    required = {"analysis_groups", "analysis_group_items", "analysis_group_summaries"}
    return bool(required - existing or _pending_column_migrations(eng))


def _migrate(eng):
    """Apply pending ALTER statements atomically; errors must stop startup."""
    from sqlalchemy import inspect, text
    migrations = _pending_column_migrations(eng)
    if not migrations:
        return
    tables = set(inspect(eng).get_table_names())
    with eng.begin() as connection:
        for _table, sql in migrations:
            connection.execute(text(sql))
        if "comments" in tables:
            # Normalize historical taxonomies before readiness checks can
            # mistake valid legacy labels for unfinished paid work.
            connection.execute(text(
                "UPDATE comments SET sentiment_llm_label = 'support' "
                "WHERE sentiment_llm_label = 'trust'"
            ))
            connection.execute(text(
                "UPDATE comments SET sentiment_llm_label = 'concern' "
                "WHERE sentiment_llm_label = 'fear'"
            ))
            connection.execute(text(
                "UPDATE comments SET sentiment_llm_label = 'sarcasm' "
                "WHERE sentiment_llm_style = 'sarcasm' AND sentiment_llm_label IN "
                "('neutral','joy','support','anticipation','surprise','anger',"
                "'sadness','concern','disgust')"
            ))
        if {"comments", "sentiment_results"} <= tables:
            for label in (
                "neutral", "joy", "support", "anticipation", "surprise",
                "anger", "sadness", "concern", "disgust", "sarcasm",
            ):
                connection.execute(text(
                    f"UPDATE sentiment_results SET llm_{label} = ("
                    "SELECT COUNT(*) FROM comments "
                    "WHERE comments.analysis_id = sentiment_results.analysis_id "
                    f"AND comments.sentiment_llm_label = '{label}')"
                ))
            connection.execute(text(
                "UPDATE sentiment_results SET llm_trust = 0, llm_fear = 0"
            ))


def _validate_schema(eng) -> None:
    """Reject a partially created event schema instead of serving corrupted data."""
    from sqlalchemy import inspect
    required_columns = {
        "analysis_groups": {"id", "name", "description", "created_at", "updated_at"},
        "analysis_group_items": {"id", "group_id", "analysis_id", "position", "added_at"},
        "analysis_group_summaries": {
            "id", "group_id", "analysis_mode", "member_signature", "filter_json", "filter_hash",
            "input_hash", "summary_text", "provider", "model", "matched_count", "sampled_count",
            "created_at", "updated_at",
        },
    }
    inspector = inspect(eng)
    tables = set(inspector.get_table_names())
    for table, expected in required_columns.items():
        if table not in tables:
            raise RuntimeError(f"缺少数据表 {table}")
        actual = {column["name"] for column in inspector.get_columns(table)}
        missing = expected - actual
        if missing:
            raise RuntimeError(f"数据表 {table} 缺少字段：{', '.join(sorted(missing))}")
