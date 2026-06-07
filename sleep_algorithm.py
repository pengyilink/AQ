from typing import Optional


def calculate_recovery_score(
    sleep_duration_min: Optional[int],
    deep_sleep_min: Optional[int],
    rem_sleep_min: Optional[int],
    awake_min: Optional[int],
    hrv_avg: Optional[float],
    resting_hr: Optional[int],
    respiratory_rate: Optional[float],
    hrv_7day_avg: Optional[float] = None,
    rhr_7day_avg: Optional[int] = None,
) -> dict:
    """
    Weighted recovery score 0-100 inspired by WHOOP methodology.

    Components:
    - HRV vs 7-day baseline: 35 pts (most important signal)
      ratio = hrv_avg / baseline; score = min(ratio, 1.4)/1.4 * 35
    - Resting HR vs baseline: 25 pts
      diff = baseline_hr - resting_hr; score = clamp(12.5 + diff*2.5, 0, 25)
    - Sleep performance: 25 pts
      perf = min(sleep_duration_min/480, 1.1); score = perf * 25
    - Sleep stage quality: 15 pts
      deep_pts = min(deep_pct/0.20, 1.2)*7.5; rem_pts = min(rem_pct/0.22, 1.2)*7.5

    Returns dict with score, category, category_label, and component breakdown.
    """
    components = {
        "hrv": 0.0,
        "resting_hr": 0.0,
        "sleep_performance": 0.0,
        "sleep_stages": 0.0,
    }

    # ── HRV component (35 pts) ────────────────────────────────────────────────
    if hrv_avg is not None and hrv_avg > 0:
        if hrv_7day_avg and hrv_7day_avg > 0:
            ratio = hrv_avg / hrv_7day_avg
        else:
            # No baseline: award proportional score based on reasonable HRV range
            # Average adult HRV ~50ms; we treat that as neutral (ratio 1.0)
            ratio = hrv_avg / 50.0
        hrv_score = (min(ratio, 1.4) / 1.4) * 35.0
        components["hrv"] = round(hrv_score, 1)
    else:
        # No HRV data: award partial credit (neutral 50% of component)
        components["hrv"] = 17.5

    # ── Resting HR component (25 pts) ────────────────────────────────────────
    if resting_hr is not None and resting_hr > 0:
        if rhr_7day_avg and rhr_7day_avg > 0:
            baseline_hr = rhr_7day_avg
        else:
            # No baseline: use population average ~60 bpm as neutral reference
            baseline_hr = 60.0
        diff = baseline_hr - resting_hr
        rhr_score = max(0.0, min(12.5 + diff * 2.5, 25.0))
        components["resting_hr"] = round(rhr_score, 1)
    else:
        # No RHR data: award neutral partial credit
        components["resting_hr"] = 12.5

    # ── Sleep performance component (25 pts) ─────────────────────────────────
    if sleep_duration_min is not None and sleep_duration_min > 0:
        perf = min(sleep_duration_min / 480.0, 1.1)
        sleep_score = perf * 25.0
        components["sleep_performance"] = round(sleep_score, 1)
    else:
        components["sleep_performance"] = 0.0

    # ── Sleep stage quality component (15 pts) ────────────────────────────────
    total_sleep = sleep_duration_min if (sleep_duration_min and sleep_duration_min > 0) else None

    if total_sleep and total_sleep > 0 and (deep_sleep_min is not None or rem_sleep_min is not None):
        deep_min_val = deep_sleep_min if deep_sleep_min is not None else 0
        rem_min_val = rem_sleep_min if rem_sleep_min is not None else 0

        deep_pct = deep_min_val / total_sleep
        rem_pct = rem_min_val / total_sleep

        deep_pts = min(deep_pct / 0.20, 1.2) * 7.5
        rem_pts = min(rem_pct / 0.22, 1.2) * 7.5
        stage_score = deep_pts + rem_pts
        components["sleep_stages"] = round(stage_score, 1)
    else:
        # No stage data: award neutral partial credit
        components["sleep_stages"] = 7.5

    # ── Total score ───────────────────────────────────────────────────────────
    total = sum(components.values())
    score = round(max(0.0, min(total, 100.0)))

    if score >= 67:
        category = "green"
        category_label = "优秀"
    elif score >= 34:
        category = "yellow"
        category_label = "适中"
    else:
        category = "red"
        category_label = "偏低"

    return {
        "score": score,
        "category": category,
        "category_label": category_label,
        "components": components,
    }


def generate_insights(
    recovery_dict: dict,
    sleep_duration_min: Optional[int],
    deep_min: Optional[int],
    rem_min: Optional[int],
    hrv: Optional[float],
    resting_hr: Optional[int],
) -> list:
    """
    Return 3-5 Chinese-language insight strings based on recovery scores and
    individual health metrics.
    """
    insights = []
    score = recovery_dict.get("score", 0)
    category = recovery_dict.get("category", "red")
    components = recovery_dict.get("components", {})

    # Overall recovery insight
    if score >= 67:
        insights.append("今日恢复状态优秀，适合高强度训练")
    elif score >= 34:
        insights.append("今日恢复状态适中，建议进行中等强度训练")
    else:
        insights.append("今日恢复状态偏低，建议以轻度恢复训练为主")

    # Sleep duration insight
    if sleep_duration_min is not None:
        if sleep_duration_min < 360:
            insights.append("睡眠时长不足，建议补充睡眠或今日早睡")
        elif sleep_duration_min >= 480:
            insights.append("睡眠时长充足，睡眠量达标")

    # Deep sleep insight
    if deep_min is not None:
        if deep_min < 60:
            insights.append("深度睡眠偏少，可降低卧室温度改善（建议18-20°C）")
        elif deep_min >= 90:
            insights.append("深度睡眠质量好，身体修复充分")

    # REM sleep insight
    if rem_min is not None and sleep_duration_min and sleep_duration_min > 0:
        rem_pct = rem_min / sleep_duration_min
        if rem_pct < 0.18:
            insights.append("REM睡眠偏少，尝试保持规律作息时间以提升睡眠质量")

    # HRV insight
    if hrv is not None:
        hrv_comp = components.get("hrv", 17.5)
        if hrv_comp < 14.0:
            insights.append("HRV偏低，神经系统处于较高压力状态，建议放松恢复")
        elif hrv_comp >= 28.0:
            insights.append("HRV表现良好，自主神经系统恢复充分")

    # Resting HR insight
    if resting_hr is not None:
        rhr_comp = components.get("resting_hr", 12.5)
        if rhr_comp < 8.0:
            insights.append("静息心率偏高，身体仍在应激状态，注意压力管理")

    # Ensure we return 3-5 insights
    if len(insights) < 3:
        fallbacks = [
            "保持规律的睡眠时间有助于改善睡眠质量",
            "睡前避免蓝光屏幕可提升睡眠深度",
            "记录每日健康数据有助于发现身体规律",
        ]
        for fb in fallbacks:
            if len(insights) >= 3:
                break
            if fb not in insights:
                insights.append(fb)

    return insights[:5]
