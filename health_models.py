from sqlalchemy import Column, Integer, String, Float, Date, DateTime
from sqlalchemy.sql import func
from database import Base
import datetime


class SleepRecord(Base):
    __tablename__ = "sleep_records"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, unique=True)
    bed_time = Column(String(5), nullable=True)         # HH:MM
    wake_time = Column(String(5), nullable=True)        # HH:MM
    total_duration_min = Column(Integer, nullable=True)  # time in bed
    sleep_duration_min = Column(Integer, nullable=True)  # actual sleep
    deep_sleep_min = Column(Integer, nullable=True)
    rem_sleep_min = Column(Integer, nullable=True)
    light_sleep_min = Column(Integer, nullable=True)
    awake_min = Column(Integer, nullable=True)
    hrv_avg = Column(Float, nullable=True)              # ms
    resting_hr = Column(Integer, nullable=True)         # bpm
    respiratory_rate = Column(Float, nullable=True)     # breaths/min
    spo2 = Column(Float, nullable=True)                 # %
    source = Column(String(20), nullable=False, default="manual")  # "manual" or "apple_watch"
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
