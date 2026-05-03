from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text, BigInteger, func
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, timedelta

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    username = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

class Card(Base):
    __tablename__ = "cards"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    question = Column(Text, nullable=False)
    reference_answer = Column(Text, nullable=False)
    category = Column(String)
    interval = Column(Integer, default=0)
    repetitions = Column(Integer, default=0)
    ease_factor = Column(Float, default=2.5)
    due_date = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="new")

engine = create_engine("sqlite:///exam_bot.db")
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)