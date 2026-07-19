"""数据库模型"""

from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, Float, DateTime, ForeignKey, create_engine
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker

DB_URL = "sqlite:///data.db"
engine = create_engine(DB_URL, echo=False)
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
    error_msg = Column(Text)
    created_at = Column(DateTime, default=datetime.now)

    comments = relationship("Comment", back_populates="analysis", cascade="all, delete-orphan")
    sentiment = relationship("SentimentResult", back_populates="analysis", uselist=False, cascade="all, delete-orphan")


class Comment(Base):
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    analysis_id = Column(Integer, ForeignKey("analyses.id"), nullable=False, index=True)
    rpid = Column(Integer, nullable=False)
    username = Column(String(100))
    gender = Column(String(10))
    ip_location = Column(String(50))
    content = Column(Text)
    likes = Column(Integer, default=0)
    sentiment_label = Column(String(10))
    sentiment_score = Column(Float)
    sentiment_llm_label = Column(String(20), default="")
    post_time = Column(DateTime, nullable=False)

    analysis = relationship("Analysis", back_populates="comments")


class SentimentResult(Base):
    __tablename__ = "sentiment_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    analysis_id = Column(Integer, ForeignKey("analyses.id"), nullable=False, unique=True)
    positive_count = Column(Integer, default=0)
    negative_count = Column(Integer, default=0)
    neutral_count = Column(Integer, default=0)
    llm_joy = Column(Integer, default=0)
    llm_anger = Column(Integer, default=0)
    llm_sadness = Column(Integer, default=0)
    llm_surprise = Column(Integer, default=0)
    llm_fear = Column(Integer, default=0)
    llm_disgust = Column(Integer, default=0)
    llm_anticipation = Column(Integer, default=0)
    llm_trust = Column(Integer, default=0)

    analysis = relationship("Analysis", back_populates="sentiment")


def init_db():
    """Initialize database tables"""
    import os
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data.db")
    eng = create_engine(f"sqlite:///{db_path}", echo=False)
    Base.metadata.create_all(eng)
    _migrate(eng)

def _migrate(eng):
    """Add missing columns to existing tables (best-effort, errors logged)."""
    from sqlalchemy import text, inspect
    import logging
    logger = logging.getLogger("migrate")
    inspector = inspect(eng)
    migrations = []

    if "analyses" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("analyses")}
        if "mode" not in cols:
            migrations.append(("analyses", "ALTER TABLE analyses ADD COLUMN mode VARCHAR(10) DEFAULT 'nlp'"))
    if "comments" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("comments")}
        if "sentiment_llm_label" not in cols:
            migrations.append(("comments", "ALTER TABLE comments ADD COLUMN sentiment_llm_label VARCHAR(20) DEFAULT ''"))
    if "sentiment_results" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("sentiment_results")}
        llm_fields = [
            "llm_joy", "llm_anger", "llm_sadness", "llm_surprise",
            "llm_fear", "llm_disgust", "llm_anticipation", "llm_trust",
        ]
        for field in llm_fields:
            if field not in cols:
                migrations.append(("sentiment_results", f"ALTER TABLE sentiment_results ADD COLUMN {field} INTEGER DEFAULT 0"))

    for table, sql in migrations:
        try:
            with eng.connect() as conn:
                conn.execute(text(sql))
                conn.commit()
        except Exception as e:
            logger.warning(f"Migration skipped ({table}): {e}")
