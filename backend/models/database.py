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
    post_time = Column(DateTime, nullable=False)

    analysis = relationship("Analysis", back_populates="comments")


class SentimentResult(Base):
    __tablename__ = "sentiment_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    analysis_id = Column(Integer, ForeignKey("analyses.id"), nullable=False, unique=True)
    positive_count = Column(Integer, default=0)
    negative_count = Column(Integer, default=0)
    neutral_count = Column(Integer, default=0)

    analysis = relationship("Analysis", back_populates="sentiment")


def init_db():
    """Initialize database tables"""
    import os
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data.db")
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    Base.metadata.create_all(engine)
