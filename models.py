from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Float
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True)
    username = Column(String)

class Card(Base):
    __tablename__ = 'cards'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    question = Column(Text)
    reference_answer = Column(Text)
    category = Column(String)
    status = Column(String, default="new")
    due_date = Column(DateTime, default=datetime.utcnow)
    interval = Column(Integer, default=1)
    repetitions = Column(Integer, default=0)
    ease_factor = Column(Float, default=2.5)
    last_score = Column(Integer, nullable=True)
    fail_count = Column(Integer, default=0)
    mnemonic = Column(Text, nullable=True)
    connections = Column(Text, nullable=True)
    case_text = Column(Text, nullable=True)
    full_answer = Column(Text, nullable=True)

engine = create_engine("sqlite:///exam_bot.db")
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
