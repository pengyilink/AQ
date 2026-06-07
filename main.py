import os
import json
import datetime
from typing import Optional, List

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel

import models
import health_models
import database
from sleep_algorithm import calculate_recovery_score, generate_insights

# Create tables for both models
models.Base.metadata.create_all(bind=database.engine)
health_models.Base.metadata.create_all(bind=database.engine)

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


class SleepCreate(BaseModel):
    date: Optional[datetime.date] = None
    bed_time: Optional[str] = None
    wake_time: Optional[str] = None
    total_duration_min: Optional[int] = None
    sleep_duration_min: Optional[int] = None
    deep_sleep_min: Optional[int] = None
    rem_sleep_min: Optional[int] = None
    light_sleep_min: Optional[int] = None
    awake_min: Optional[int] = None
    hrv_avg: Optional[float] = None
    resting_hr: Optional[int] = None
    respiratory_rate: Optional[float] = None
    spo2: Optional[float] = None
    source: Optional[str] = "manual"


class AppleWatchCreate(BaseModel):
    date: Optional[datetime.date] = None
    bed_time: Optional[str] = None
    wake_time: Optional[str] = None
    total_duration_min: Optional[int] = None
    sleep_duration_min: Optional[int] = None
    deep_sleep_min: Optional[int] = None
    rem_sleep_min: Optional[int] = None
    light_sleep_min: Optional[int] = None
    awake_min: Optional[int] = None
    hrv_avg: Optional[float] = None
    resting_hr: Optional[int] = None
    respiratory_rate: Optional[float] = None
    spo2: Optional[float] = None


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    include_health_context: bool = False


# ── Helper functions ──────────────────────────────────────────────────────────

def _to_date(v):
    if isinstance(v, datetime.date):
        return v
    return datetime.date.fromisoformat(str(v))


def _get_7day_baselines(db: Session, exclude_date: Optional[datetime.date] = None):
    """Return (hrv_7day_avg, rhr_7day_avg) from last 7 sleep records."""
    q = db.query(health_models.SleepRecord).order_by(
        health_models.SleepRecord.date.desc()
    )
    if exclude_date:
        q = q.filter(health_models.SleepRecord.date != exclude_date)
    records = q.limit(7).all()

    hrv_vals = [r.hrv_avg for r in records if r.hrv_avg is not None]
    rhr_vals = [r.resting_hr for r in records if r.resting_hr is not None]

    hrv_7day = sum(hrv_vals) / len(hrv_vals) if hrv_vals else None
    rhr_7day = round(sum(rhr_vals) / len(rhr_vals)) if rhr_vals else None
    return hrv_7day, rhr_7day


def _record_to_dict(record: health_models.SleepRecord, db: Session) -> dict:
    """Serialize a SleepRecord to dict with recovery score attached."""
    hrv_7day, rhr_7day = _get_7day_baselines(db, exclude_date=record.date)
    recovery = calculate_recovery_score(
        sleep_duration_min=record.sleep_duration_min,
        deep_sleep_min=record.deep_sleep_min,
        rem_sleep_min=record.rem_sleep_min,
        awake_min=record.awake_min,
        hrv_avg=record.hrv_avg,
        resting_hr=record.resting_hr,
        respiratory_rate=record.respiratory_rate,
        hrv_7day_avg=hrv_7day,
        rhr_7day_avg=rhr_7day,
    )
    return {
        "id": record.id,
        "date": str(record.date),
        "bed_time": record.bed_time,
        "wake_time": record.wake_time,
        "total_duration_min": record.total_duration_min,
        "sleep_duration_min": record.sleep_duration_min,
        "deep_sleep_min": record.deep_sleep_min,
        "rem_sleep_min": record.rem_sleep_min,
        "light_sleep_min": record.light_sleep_min,
        "awake_min": record.awake_min,
        "hrv_avg": record.hrv_avg,
        "resting_hr": record.resting_hr,
        "respiratory_rate": record.respiratory_rate,
        "spo2": record.spo2,
        "source": record.source,
        "created_at": str(record.created_at),
        "recovery": recovery,
    }


def _upsert_sleep(db: Session, payload_dict: dict, source: str) -> health_models.SleepRecord:
    """Insert or update a sleep record for the given date."""
    target_date = payload_dict.get("date") or datetime.date.today()
    if isinstance(target_date, str):
        target_date = datetime.date.fromisoformat(target_date)

    existing = db.query(health_models.SleepRecord).filter(
        health_models.SleepRecord.date == target_date
    ).first()

    if existing:
        for field in [
            "bed_time", "wake_time", "total_duration_min", "sleep_duration_min",
            "deep_sleep_min", "rem_sleep_min", "light_sleep_min", "awake_min",
            "hrv_avg", "resting_hr", "respiratory_rate", "spo2",
        ]:
            val = payload_dict.get(field)
            if val is not None:
                setattr(existing, field, val)
        existing.source = source
        db.commit()
        db.refresh(existing)
        return existing
    else:
        record = health_models.SleepRecord(
            date=target_date,
            bed_time=payload_dict.get("bed_time"),
            wake_time=payload_dict.get("wake_time"),
            total_duration_min=payload_dict.get("total_duration_min"),
            sleep_duration_min=payload_dict.get("sleep_duration_min"),
            deep_sleep_min=payload_dict.get("deep_sleep_min"),
            rem_sleep_min=payload_dict.get("rem_sleep_min"),
            light_sleep_min=payload_dict.get("light_sleep_min"),
            awake_min=payload_dict.get("awake_min"),
            hrv_avg=payload_dict.get("hrv_avg"),
            resting_hr=payload_dict.get("resting_hr"),
            respiratory_rate=payload_dict.get("respiratory_rate"),
            spo2=payload_dict.get("spo2"),
            source=source,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record


# ── Root route ────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return FileResponse("static/index.html")


# ── Workout endpoints ─────────────────────────────────────────────────────────

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

    total_days = (
        db.query(func.count(func.distinct(models.WorkoutRecord.date)))
        .scalar()
    ) or 0

    total_records = db.query(func.count(models.WorkoutRecord.id)).scalar() or 0

    week_start = today - datetime.timedelta(days=today.weekday())
    this_week = (
        db.query(func.count(func.distinct(models.WorkoutRecord.date)))
        .filter(models.WorkoutRecord.date >= week_start)
        .scalar()
    ) or 0

    all_dates = (
        db.query(func.distinct(models.WorkoutRecord.date))
        .order_by(models.WorkoutRecord.date.desc())
        .all()
    )
    date_set = {_to_date(row[0]) for row in all_dates}

    streak = 0
    check = today
    if check not in date_set:
        check = today - datetime.timedelta(days=1)
    while check in date_set:
        streak += 1
        check -= datetime.timedelta(days=1)

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


# ── Sleep / Health endpoints ──────────────────────────────────────────────────

@app.post("/api/health/sleep")
def create_sleep_record(
    payload: SleepCreate,
    db: Session = Depends(database.get_db)
):
    payload_dict = payload.model_dump()
    source = payload_dict.pop("source", None) or "manual"
    record = _upsert_sleep(db, payload_dict, source)
    return _record_to_dict(record, db)


@app.get("/api/health/sleep")
def get_sleep_records(
    limit: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(database.get_db)
):
    records = (
        db.query(health_models.SleepRecord)
        .order_by(health_models.SleepRecord.date.desc())
        .limit(limit)
        .all()
    )
    return [_record_to_dict(r, db) for r in records]


@app.get("/api/health/sleep/{date_str}")
def get_sleep_record_by_date(
    date_str: str,
    db: Session = Depends(database.get_db)
):
    try:
        target_date = datetime.date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    record = db.query(health_models.SleepRecord).filter(
        health_models.SleepRecord.date == target_date
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="No sleep record found for this date.")

    hrv_7day, rhr_7day = _get_7day_baselines(db, exclude_date=target_date)
    recovery = calculate_recovery_score(
        sleep_duration_min=record.sleep_duration_min,
        deep_sleep_min=record.deep_sleep_min,
        rem_sleep_min=record.rem_sleep_min,
        awake_min=record.awake_min,
        hrv_avg=record.hrv_avg,
        resting_hr=record.resting_hr,
        respiratory_rate=record.respiratory_rate,
        hrv_7day_avg=hrv_7day,
        rhr_7day_avg=rhr_7day,
    )
    insights = generate_insights(
        recovery_dict=recovery,
        sleep_duration_min=record.sleep_duration_min,
        deep_min=record.deep_sleep_min,
        rem_min=record.rem_sleep_min,
        hrv=record.hrv_avg,
        resting_hr=record.resting_hr,
    )
    result = _record_to_dict(record, db)
    result["insights"] = insights
    return result


@app.get("/api/recovery/today")
def get_today_recovery(db: Session = Depends(database.get_db)):
    today = datetime.date.today()

    # Try today first, then fall back to most recent record
    record = db.query(health_models.SleepRecord).filter(
        health_models.SleepRecord.date == today
    ).first()

    if not record:
        record = (
            db.query(health_models.SleepRecord)
            .order_by(health_models.SleepRecord.date.desc())
            .first()
        )

    hrv_7day, rhr_7day = _get_7day_baselines(db)

    if not record:
        # No data at all — return neutral state
        return {
            "date": str(today),
            "has_data": False,
            "recovery": {
                "score": 0,
                "category": "red",
                "category_label": "暂无数据",
                "components": {"hrv": 0, "resting_hr": 0, "sleep_performance": 0, "sleep_stages": 0},
            },
            "hrv_7day_avg": hrv_7day,
            "rhr_7day_avg": rhr_7day,
            "insights": ["记录您的睡眠数据以获取每日恢复评分", "在「睡眠」标签页输入昨晚的睡眠信息", "连接Apple Watch可自动同步健康数据"],
        }

    recovery = calculate_recovery_score(
        sleep_duration_min=record.sleep_duration_min,
        deep_sleep_min=record.deep_sleep_min,
        rem_sleep_min=record.rem_sleep_min,
        awake_min=record.awake_min,
        hrv_avg=record.hrv_avg,
        resting_hr=record.resting_hr,
        respiratory_rate=record.respiratory_rate,
        hrv_7day_avg=hrv_7day,
        rhr_7day_avg=rhr_7day,
    )
    insights = generate_insights(
        recovery_dict=recovery,
        sleep_duration_min=record.sleep_duration_min,
        deep_min=record.deep_sleep_min,
        rem_min=record.rem_sleep_min,
        hrv=record.hrv_avg,
        resting_hr=record.resting_hr,
    )
    return {
        "date": str(record.date),
        "has_data": True,
        "sleep_duration_min": record.sleep_duration_min,
        "hrv_avg": record.hrv_avg,
        "resting_hr": record.resting_hr,
        "spo2": record.spo2,
        "respiratory_rate": record.respiratory_rate,
        "recovery": recovery,
        "hrv_7day_avg": hrv_7day,
        "rhr_7day_avg": rhr_7day,
        "insights": insights,
    }


@app.post("/api/health/apple-watch")
def apple_watch_sync(
    payload: AppleWatchCreate,
    db: Session = Depends(database.get_db)
):
    """Idempotent endpoint for Apple Shortcuts / Apple Watch data push."""
    payload_dict = payload.model_dump()
    record = _upsert_sleep(db, payload_dict, source="apple_watch")
    return _record_to_dict(record, db)


# ── AI Chat endpoint ──────────────────────────────────────────────────────────

def _build_health_context(db: Session) -> str:
    """Build a health context string for the AI system prompt."""
    today = datetime.date.today()

    # Today's recovery
    sleep_record = db.query(health_models.SleepRecord).filter(
        health_models.SleepRecord.date == today
    ).first()
    if not sleep_record:
        sleep_record = (
            db.query(health_models.SleepRecord)
            .order_by(health_models.SleepRecord.date.desc())
            .first()
        )

    hrv_7day, rhr_7day = _get_7day_baselines(db)

    lines = [f"今日日期：{today}"]

    if sleep_record:
        recovery = calculate_recovery_score(
            sleep_duration_min=sleep_record.sleep_duration_min,
            deep_sleep_min=sleep_record.deep_sleep_min,
            rem_sleep_min=sleep_record.rem_sleep_min,
            awake_min=sleep_record.awake_min,
            hrv_avg=sleep_record.hrv_avg,
            resting_hr=sleep_record.resting_hr,
            respiratory_rate=sleep_record.respiratory_rate,
            hrv_7day_avg=hrv_7day,
            rhr_7day_avg=rhr_7day,
        )
        lines.append(f"最近睡眠记录日期：{sleep_record.date}")
        lines.append(f"恢复评分：{recovery['score']}/100（{recovery['category_label']}）")
        if sleep_record.sleep_duration_min:
            h, m = divmod(sleep_record.sleep_duration_min, 60)
            lines.append(f"睡眠时长：{h}小时{m}分钟")
        if sleep_record.deep_sleep_min:
            lines.append(f"深度睡眠：{sleep_record.deep_sleep_min}分钟")
        if sleep_record.rem_sleep_min:
            lines.append(f"REM睡眠：{sleep_record.rem_sleep_min}分钟")
        if sleep_record.hrv_avg:
            lines.append(f"HRV：{sleep_record.hrv_avg}ms")
        if hrv_7day:
            lines.append(f"7日平均HRV：{round(hrv_7day, 1)}ms")
        if sleep_record.resting_hr:
            lines.append(f"静息心率：{sleep_record.resting_hr}bpm")
        if rhr_7day:
            lines.append(f"7日平均静息心率：{rhr_7day}bpm")
        if sleep_record.spo2:
            lines.append(f"血氧SpO2：{sleep_record.spo2}%")
        if sleep_record.respiratory_rate:
            lines.append(f"呼吸频率：{sleep_record.respiratory_rate}次/分")
    else:
        lines.append("暂无睡眠/健康数据记录")

    # Recent workouts (last 3)
    recent_workouts = (
        db.query(models.WorkoutRecord)
        .order_by(models.WorkoutRecord.date.desc(), models.WorkoutRecord.created_at.desc())
        .limit(3)
        .all()
    )
    if recent_workouts:
        lines.append("\n最近训练记录：")
        for w in recent_workouts:
            parts = [f"{w.date} {w.exercise_name}"]
            if w.duration_min:
                parts.append(f"{w.duration_min}分钟")
            if w.sets and w.reps:
                parts.append(f"{w.sets}组×{w.reps}次")
            if w.weight_kg:
                parts.append(f"{w.weight_kg}kg")
            lines.append("- " + " ".join(parts))
    else:
        lines.append("暂无训练记录")

    return "\n".join(lines)


@app.post("/api/ai/chat")
async def ai_chat(
    payload: ChatRequest,
    db: Session = Depends(database.get_db)
):
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail=(
                "ANTHROPIC_API_KEY 未配置。请在服务器环境变量中设置 ANTHROPIC_API_KEY。"
                " 可通过 export ANTHROPIC_API_KEY=sk-ant-... 命令设置。"
            ),
        )

    try:
        import anthropic
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="anthropic SDK 未安装。请运行: pip install anthropic>=0.40.0",
        )

    system_prompt = (
        "你是一位专业的健康与运动教练，专注于恢复科学。"
        "你能根据用户的睡眠数据、HRV、心率等健康指标提供个性化的训练和恢复建议。"
        "回答要简洁、专业、以数据为基础，使用中文。"
        "如果用户的恢复分数较低，建议减少训练强度；分数高时，可以推荐挑战性训练。"
    )

    if payload.include_health_context:
        health_ctx = _build_health_context(db)
        system_prompt += f"\n\n用户当前健康数据：\n{health_ctx}"

    messages = [{"role": m.role, "content": m.content} for m in payload.messages]

    client = anthropic.Anthropic(api_key=api_key)

    def stream_response():
        try:
            with client.messages.stream(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                system=system_prompt,
                messages=messages,
            ) as stream:
                for text_chunk in stream.text_stream:
                    data = json.dumps({"text": text_chunk}, ensure_ascii=False)
                    yield f"data: {data}\n\n"
            yield "data: [DONE]\n\n"
        except anthropic.AuthenticationError:
            err = json.dumps({"error": "API Key 无效，请检查 ANTHROPIC_API_KEY 配置"}, ensure_ascii=False)
            yield f"data: {err}\n\n"
        except anthropic.RateLimitError:
            err = json.dumps({"error": "API 请求过于频繁，请稍后再试"}, ensure_ascii=False)
            yield f"data: {err}\n\n"
        except Exception as e:
            err = json.dumps({"error": f"AI 服务暂时不可用：{str(e)}"}, ensure_ascii=False)
            yield f"data: {err}\n\n"

    return StreamingResponse(
        stream_response(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
