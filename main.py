from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, cast, Date
from pydantic import BaseModel
from typing import Optional
import datetime
import models
import database

# Create tables
models.Base.metadata.create_all(bind=database.engine)

app = FastAPI(title="Fitness Check-in App")

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class WorkoutCreate(BaseModel):
    date: Optional[datetime.date] = None
    exercise_name: str
    sets: Optional[int] = None
    reps: Optional[int] = None
    weight_kg: Optional[float] = None
    duration_min: Optional[int] = None
    notes: Optional[str] = None


class WorkoutResponse(BaseModel):
    id: int
    date: datetime.date
    exercise_name: str
    sets: Optional[int]
    reps: Optional[int]
    weight_kg: Optional[float]
    duration_min: Optional[int]
    notes: Optional[str]
    created_at: datetime.datetime

    class Config:
        from_attributes = True


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return FileResponse("static/index.html")


@app.post("/api/checkin", response_model=WorkoutResponse)
def create_checkin(
    payload: WorkoutCreate,
    db: Session = Depends(database.get_db)
):
    record = models.WorkoutRecord(
        date=payload.date or datetime.date.today(),
        exercise_name=payload.exercise_name,
        sets=payload.sets,
        reps=payload.reps,
        weight_kg=payload.weight_kg,
        duration_min=payload.duration_min,
        notes=payload.notes,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@app.get("/api/records", response_model=list[WorkoutResponse])
def get_records(
    date: Optional[datetime.date] = Query(default=None),
    db: Session = Depends(database.get_db)
):
    q = db.query(models.WorkoutRecord)
    if date:
        q = q.filter(models.WorkoutRecord.date == date)
    records = q.order_by(models.WorkoutRecord.created_at.desc()).all()
    return records


@app.get("/api/stats")
def get_stats(db: Session = Depends(database.get_db)):
    today = datetime.date.today()

    # Total check-ins (distinct days)
    total_days = (
        db.query(func.count(func.distinct(models.WorkoutRecord.date)))
        .scalar()
    ) or 0

    # Total records
    total_records = db.query(func.count(models.WorkoutRecord.id)).scalar() or 0

    # This week (Mon–Sun)
    week_start = today - datetime.timedelta(days=today.weekday())
    this_week = (
        db.query(func.count(func.distinct(models.WorkoutRecord.date)))
        .filter(models.WorkoutRecord.date >= week_start)
        .scalar()
    ) or 0

    # Current streak — walk backwards from today
    all_dates = (
        db.query(func.distinct(models.WorkoutRecord.date))
        .order_by(models.WorkoutRecord.date.desc())
        .all()
    )
    # Normalise to datetime.date regardless of whether SQLite returns str or date
    def _to_date(v):
        if isinstance(v, datetime.date):
            return v
        return datetime.date.fromisoformat(str(v))

    date_set = {_to_date(row[0]) for row in all_dates}

    streak = 0
    check = today
    # If today not yet checked in, still count from yesterday
    if check not in date_set:
        check = today - datetime.timedelta(days=1)
    while check in date_set:
        streak += 1
        check -= datetime.timedelta(days=1)

    # Per-day record counts for this week (Mon=0 … Sun=6)
    week_counts = []
    for i in range(7):
        day = week_start + datetime.timedelta(days=i)
        count = (
            db.query(func.count(models.WorkoutRecord.id))
            .filter(models.WorkoutRecord.date == day)
            .scalar()
        ) or 0
        week_counts.append(count)

    return {
        "total_days": total_days,
        "total_records": total_records,
        "current_streak": streak,
        "this_week": this_week,
        "week_counts": week_counts,
        "today": str(today),
        "checked_in_today": today in date_set,
    }


@app.delete("/api/records/{record_id}")
def delete_record(record_id: int, db: Session = Depends(database.get_db)):
    record = db.query(models.WorkoutRecord).filter(
        models.WorkoutRecord.id == record_id
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")
    db.delete(record)
    db.commit()
    return {"message": "Deleted successfully"}
