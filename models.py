from sqlalchemy import Column, Integer, String, Float, Date, DateTime, Text
from sqlalchemy.sql import func
from database import Base
import datetime


class WorkoutRecord(Base):
    __tablename__ = "workout_records"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, default=datetime.date.today)
    exercise_name = Column(String(100), nullable=False)
    sets = Column(Integer, nullable=True)
    reps = Column(Integer, nullable=True)
    weight_kg = Column(Float, nullable=True)
    duration_min = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
