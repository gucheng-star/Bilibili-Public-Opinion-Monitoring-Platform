"""数据库模型"""

from datetime import datetime
import os
import sqlite3
from pathlib import Path

from sqlalchemy import Column, Integer, String, Text, Float, DateTime, ForeignKey, UniqueConstraint, create_engine, event
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker

from services.runtime_paths import database_path
from services.sentiment_contract import (
    LLM_SENTIMENT_SCHEMA_NONE,
    LLM_SENTIMENT_SCHEMA_V1,
    LLM_SENTIMENT_SCHEMA_V2,
    V1_EMOTION_LABELS,
    V2_EMOTION_LABELS,
    V2_STYLE_LABELS,
)


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
    sentiment_llm_schema_version = Column(
        Integer, nullable=False, default=LLM_SENTIMENT_SCHEMA_NONE, server_default="0",
    )
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
    sentiment_llm_schema_version = Column(
        Integer, nullable=False, default=LLM_SENTIMENT_SCHEMA_NONE, server_default="0",
    )
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
    sentiment_llm_schema_version = Column(
        Integer, nullable=False, default=LLM_SENTIMENT_SCHEMA_NONE, server_default="0",
    )

    analysis = relationship("Analysis", back_populates="sentiment")


class AISummary(Base):
    __tablename__ = "ai_summaries"
    __table_args__ = (
        UniqueConstraint("analysis_id", "filter_hash", "interpretation_view", "report_mode", name="uq_ai_summary_analysis_filter_view_mode"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    analysis_id = Column(Integer, ForeignKey("analyses.id"), nullable=False, index=True)
    filter_json = Column(Text, nullable=False)
    filter_hash = Column(String(64), nullable=False)
    interpretation_view = Column(String(30), nullable=False, default="public_opinion", server_default="public_opinion")
    report_mode = Column(String(10), nullable=False, default="quick", server_default="quick")
    thinking_status = Column(String(20), nullable=False, default="disabled", server_default="disabled")
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
        if "sentiment_llm_schema_version" not in cols:
            migrations.append((
                "analyses",
                "ALTER TABLE analyses ADD COLUMN sentiment_llm_schema_version INTEGER NOT NULL DEFAULT 0",
            ))
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
        if "sentiment_llm_schema_version" not in cols:
            migrations.append((
                "comments",
                "ALTER TABLE comments ADD COLUMN sentiment_llm_schema_version INTEGER NOT NULL DEFAULT 0",
            ))
    if "sentiment_results" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("sentiment_results")}
        llm_fields = [
            "llm_neutral", "llm_joy", "llm_support", "llm_anger", "llm_sadness", "llm_surprise",
            "llm_fear", "llm_disgust", "llm_anticipation", "llm_concern", "llm_trust", "llm_sarcasm",
        ]
        for field in llm_fields:
            if field not in cols:
                migrations.append(("sentiment_results", f"ALTER TABLE sentiment_results ADD COLUMN {field} INTEGER DEFAULT 0"))
        if "sentiment_llm_schema_version" not in cols:
            migrations.append((
                "sentiment_results",
                "ALTER TABLE sentiment_results ADD COLUMN sentiment_llm_schema_version INTEGER NOT NULL DEFAULT 0",
            ))

    return migrations


def _ai_summary_role_migration_required(eng) -> bool:
    from sqlalchemy import inspect
    inspector = inspect(eng)
    if "ai_summaries" not in inspector.get_table_names():
        return False
    columns = {column["name"] for column in inspector.get_columns("ai_summaries")}
    return not {"interpretation_view", "report_mode", "thinking_status"} <= columns


def _schema_change_required(eng) -> bool:
    """Check before create_all so every mutating upgrade is backed up first."""
    source = Path(DB_PATH)
    if not source.exists():
        return False
    from sqlalchemy import inspect
    existing = set(inspect(eng).get_table_names())
    required = {"analysis_groups", "analysis_group_items", "analysis_group_summaries"}
    return bool(
        required - existing
        or _pending_column_migrations(eng)
        or _pending_llm_sentiment_version_backfill(eng)
        or _ai_summary_role_migration_required(eng)
    )


def _pending_llm_sentiment_version_backfill(eng) -> bool:
    """Return whether the version migration would update an already-current schema."""
    from sqlalchemy import inspect, text

    inspector = inspect(eng)
    tables = set(inspector.get_table_names())
    columns = {
        table: {column["name"] for column in inspector.get_columns(table)}
        for table in {"analyses", "comments", "sentiment_results"} & tables
    }

    # Missing columns are handled by _pending_column_migrations(), which is
    # already a backup trigger.  Do not query a partially known schema here.
    with eng.connect() as connection:
        if {"comments"} <= tables and "sentiment_llm_schema_version" in columns["comments"]:
            legacy_labels = ", ".join(f"'{label}'" for label in sorted(V1_EMOTION_LABELS))
            if connection.execute(text(
                "SELECT EXISTS (SELECT 1 FROM comments "
                "WHERE sentiment_llm_schema_version IS NULL "
                "OR (sentiment_llm_schema_version = 0 "
                f"AND sentiment_llm_label IN ({legacy_labels})))"
            )).scalar():
                return True

        if {"analyses"} <= tables and "sentiment_llm_schema_version" in columns["analyses"]:
            if connection.execute(text(
                "SELECT EXISTS (SELECT 1 FROM analyses "
                "WHERE sentiment_llm_schema_version IS NULL)"
            )).scalar():
                return True

        if {"sentiment_results"} <= tables and "sentiment_llm_schema_version" in columns["sentiment_results"]:
            if connection.execute(text(
                "SELECT EXISTS (SELECT 1 FROM sentiment_results "
                "WHERE sentiment_llm_schema_version IS NULL)"
            )).scalar():
                return True

        if (
            {"analyses", "comments"} <= tables
            and "sentiment_llm_schema_version" in columns["analyses"]
            and "sentiment_llm_schema_version" in columns["comments"]
            and connection.execute(text(
                "SELECT EXISTS (SELECT 1 FROM analyses "
                "WHERE sentiment_llm_schema_version = 0 "
                "AND EXISTS (SELECT 1 FROM comments "
                "            WHERE comments.analysis_id = analyses.id) "
                "AND NOT EXISTS (SELECT 1 FROM comments "
                "                WHERE comments.analysis_id = analyses.id "
                "                  AND comments.sentiment_llm_schema_version != 1))"
            )).scalar()
        ):
            return True

        if (
            {"analyses", "sentiment_results"} <= tables
            and "sentiment_llm_schema_version" in columns["analyses"]
            and "sentiment_llm_schema_version" in columns["sentiment_results"]
            and connection.execute(text(
                "SELECT EXISTS (SELECT 1 FROM sentiment_results "
                "WHERE sentiment_llm_schema_version = 0 "
                "AND EXISTS (SELECT 1 FROM analyses "
                "            WHERE analyses.id = sentiment_results.analysis_id "
                "              AND analyses.sentiment_llm_schema_version = 1))"
            )).scalar()
        ):
            return True

    return False


def _migrate(eng):
    """Apply pending schema and non-destructive LLM-version migrations atomically."""
    from sqlalchemy import inspect, text
    migrations = _pending_column_migrations(eng)
    needs_version_backfill = bool(migrations) or _pending_llm_sentiment_version_backfill(eng)
    tables = set(inspect(eng).get_table_names())
    with eng.begin() as connection:
        if _ai_summary_role_migration_required(eng):
            _migrate_ai_summaries_for_roles(connection)
        for _table, sql in migrations:
            connection.execute(text(sql))
        if needs_version_backfill:
            _migrate_llm_sentiment_versions(connection, tables)


def _migrate_ai_summaries_for_roles(connection) -> None:
    """Rebuild the SQLite cache table to replace its legacy uniqueness scope."""
    from sqlalchemy import text

    connection.execute(text("ALTER TABLE ai_summaries RENAME TO ai_summaries_legacy"))
    # SQLite keeps an index name when its table is renamed.  Release the
    # legacy table's generated index before creating the same index for the
    # rebuilt cache table below.
    connection.execute(text("DROP INDEX IF EXISTS ix_ai_summaries_analysis_id"))
    connection.execute(text("""
        CREATE TABLE ai_summaries (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            analysis_id INTEGER NOT NULL REFERENCES analyses (id),
            filter_json TEXT NOT NULL,
            filter_hash VARCHAR(64) NOT NULL,
            interpretation_view VARCHAR(30) NOT NULL DEFAULT 'public_opinion',
            report_mode VARCHAR(10) NOT NULL DEFAULT 'quick',
            thinking_status VARCHAR(20) NOT NULL DEFAULT 'disabled',
            input_hash VARCHAR(64) NOT NULL,
            summary_text TEXT NOT NULL,
            provider VARCHAR(30) NOT NULL,
            model VARCHAR(100) NOT NULL,
            matched_count INTEGER,
            sampled_count INTEGER,
            created_at DATETIME,
            updated_at DATETIME,
            CONSTRAINT uq_ai_summary_analysis_filter_view_mode
                UNIQUE (analysis_id, filter_hash, interpretation_view, report_mode)
        )
    """))
    connection.execute(text("""
        INSERT INTO ai_summaries (
            id, analysis_id, filter_json, filter_hash, input_hash, summary_text,
            provider, model, matched_count, sampled_count, created_at, updated_at
        ) SELECT id, analysis_id, filter_json, filter_hash, input_hash, summary_text,
            provider, model, matched_count, sampled_count, created_at, updated_at
        FROM ai_summaries_legacy
    """))
    connection.execute(text("CREATE INDEX ix_ai_summaries_analysis_id ON ai_summaries (analysis_id)"))
    connection.execute(text("DROP TABLE ai_summaries_legacy"))


def _migrate_llm_sentiment_versions(connection, tables: set[str]) -> None:
    """Mark historical complete results without rewriting their V1 payloads."""
    from sqlalchemy import text

    if "comments" in tables:
        connection.execute(text(
            "UPDATE comments SET sentiment_llm_schema_version = 0 "
            "WHERE sentiment_llm_schema_version IS NULL"
        ))
        legacy_labels = ", ".join(f"'{label}'" for label in sorted(V1_EMOTION_LABELS))
        connection.execute(text(
            "UPDATE comments SET sentiment_llm_schema_version = 1 "
            "WHERE sentiment_llm_schema_version = 0 "
            f"AND sentiment_llm_label IN ({legacy_labels})"
        ))

    if "analyses" in tables:
        connection.execute(text(
            "UPDATE analyses SET sentiment_llm_schema_version = 0 "
            "WHERE sentiment_llm_schema_version IS NULL"
        ))
    if "sentiment_results" in tables:
        connection.execute(text(
            "UPDATE sentiment_results SET sentiment_llm_schema_version = 0 "
            "WHERE sentiment_llm_schema_version IS NULL"
        ))

    if {"analyses", "comments"} <= tables:
        connection.execute(text(
            "UPDATE analyses SET sentiment_llm_schema_version = :v1 "
            "WHERE sentiment_llm_schema_version = :none "
            "AND EXISTS (SELECT 1 FROM comments "
            "            WHERE comments.analysis_id = analyses.id) "
            "AND NOT EXISTS (SELECT 1 FROM comments "
            "                WHERE comments.analysis_id = analyses.id "
            "                  AND comments.sentiment_llm_schema_version != :v1)"
        ), {"none": LLM_SENTIMENT_SCHEMA_NONE, "v1": LLM_SENTIMENT_SCHEMA_V1})

    if {"analyses", "sentiment_results"} <= tables:
        connection.execute(text(
            "UPDATE sentiment_results SET sentiment_llm_schema_version = :v1 "
            "WHERE sentiment_llm_schema_version = :none "
            "AND EXISTS (SELECT 1 FROM analyses "
            "            WHERE analyses.id = sentiment_results.analysis_id "
            "              AND analyses.sentiment_llm_schema_version = :v1)"
        ), {"none": LLM_SENTIMENT_SCHEMA_NONE, "v1": LLM_SENTIMENT_SCHEMA_V1})


def _validate_schema(eng) -> None:
    """Reject incomplete schema or invalid versioned sentiment state at startup."""
    from sqlalchemy import inspect
    required_columns = {
        "analyses": {"sentiment_llm_schema_version"},
        "comments": {"sentiment_llm_schema_version"},
        "sentiment_results": {"sentiment_llm_schema_version"},
        "analysis_groups": {"id", "name", "description", "created_at", "updated_at"},
        "analysis_group_items": {"id", "group_id", "analysis_id", "position", "added_at"},
        "analysis_group_summaries": {
            "id", "group_id", "analysis_mode", "member_signature", "filter_json", "filter_hash",
            "input_hash", "summary_text", "provider", "model", "matched_count", "sampled_count",
            "created_at", "updated_at",
        },
        "ai_summaries": {
            "id", "analysis_id", "filter_json", "filter_hash", "interpretation_view",
            "report_mode", "thinking_status", "input_hash", "summary_text", "provider",
            "model", "matched_count", "sampled_count", "created_at", "updated_at",
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
    _validate_llm_sentiment_schema_versions(eng, inspector)


def _validate_llm_sentiment_schema_versions(eng, inspector) -> None:
    """Validate the durable V1/V2 boundary without changing stored data."""
    from sqlalchemy import text

    version_column = "sentiment_llm_schema_version"
    for table in ("analyses", "comments", "sentiment_results"):
        column = next(
            item for item in inspector.get_columns(table) if item["name"] == version_column
        )
        if "INT" not in str(column["type"]).upper():
            raise RuntimeError(f"数据表 {table} 的 {version_column} 必须具有 INTEGER affinity")
        if column["nullable"]:
            raise RuntimeError(f"数据表 {table} 的 {version_column} 必须为 NOT NULL")
        if str(column["default"]).strip().strip("()'") != "0":
            raise RuntimeError(f"数据表 {table} 的 {version_column} 默认值必须为 0")

    v1_labels = ", ".join(f"'{label}'" for label in sorted(V1_EMOTION_LABELS))
    v2_emotions = ", ".join(f"'{label}'" for label in sorted(V2_EMOTION_LABELS))
    v2_styles = ", ".join(f"'{label}'" for label in sorted(V2_STYLE_LABELS))
    with eng.connect() as connection:
        for table in ("analyses", "comments", "sentiment_results"):
            if connection.execute(text(
                f"SELECT EXISTS (SELECT 1 FROM {table} "
                f"WHERE {version_column} IS NULL OR {version_column} NOT IN (0, 1, 2))"
            )).scalar():
                raise RuntimeError(f"数据表 {table} 存在非法大模型情感 Schema 版本")

        if connection.execute(text(
            "SELECT EXISTS (SELECT 1 FROM comments "
            "WHERE sentiment_llm_schema_version = :v1 "
            f"AND (sentiment_llm_label IS NULL OR sentiment_llm_label NOT IN ({v1_labels})))"
        ), {"v1": LLM_SENTIMENT_SCHEMA_V1}).scalar():
            raise RuntimeError("评论 V1 大模型情感标签非法")

        if connection.execute(text(
            "SELECT EXISTS (SELECT 1 FROM comments "
            "WHERE sentiment_llm_schema_version = :v2 "
            f"AND (sentiment_llm_label IS NULL OR sentiment_llm_label NOT IN ({v2_emotions}) "
            "OR sentiment_llm_style IS NULL "
            f"OR sentiment_llm_style NOT IN ({v2_styles})))"
        ), {"v2": LLM_SENTIMENT_SCHEMA_V2}).scalar():
            raise RuntimeError("评论 V2 大模型情感或表达风格非法")

        if connection.execute(text(
            "SELECT EXISTS (SELECT 1 FROM analyses "
            "WHERE sentiment_llm_schema_version > :none "
            "AND (NOT EXISTS (SELECT 1 FROM comments "
            "                WHERE comments.analysis_id = analyses.id) "
            "     OR EXISTS (SELECT 1 FROM comments "
            "               WHERE comments.analysis_id = analyses.id "
            "                 AND comments.sentiment_llm_schema_version "
            "                     < analyses.sentiment_llm_schema_version)))"
        ), {"none": LLM_SENTIMENT_SCHEMA_NONE}).scalar():
            raise RuntimeError("分析大模型情感 Schema 版本高于其评论覆盖范围")

        if connection.execute(text(
            "SELECT EXISTS (SELECT 1 FROM sentiment_results "
            "WHERE sentiment_llm_schema_version > :none "
            "AND NOT EXISTS (SELECT 1 FROM analyses "
            "                WHERE analyses.id = sentiment_results.analysis_id "
            "                  AND analyses.sentiment_llm_schema_version "
            "                      >= sentiment_results.sentiment_llm_schema_version))"
        ), {"none": LLM_SENTIMENT_SCHEMA_NONE}).scalar():
            raise RuntimeError("大模型情感汇总 Schema 版本高于来源分析")
