#️ analytics.py includes:
#️ 1. GET /analytics/daily?days=7  — daily breakdown for frontend graphs
#️ 2. GET /analytics/total         — lifetime aggregates + current streak
#️ 3. streak helper                — counts consecutive active study days

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from deps.database import DailyActivity, ReviewEvent, User, utc_today
from deps.security import get_current_user

router = APIRouter(prefix="/analytics", tags=["Analytics"])


#️
#️ Response Schemas
#️

class DailyActivityOut(BaseModel):
    #️ one row per day — consumed by the frontend graph component
    date: date
    cards_reviewed: int
    cards_correct: int


class TotalStatsOut(BaseModel):
    #️ lifetime aggregates across every deck the user has studied
    total_cards_reviewed: int
    overall_accuracy_pct: float
    current_streak_days: int


#️
#️ 1. Daily Analytics Endpoint
#️

@router.get("/daily", response_model=list[DailyActivityOut])
async def get_daily_analytics(
    days: int = Query(default=7, ge=1, le=365),
    user: User = Depends(get_current_user),
):
    #️ returns per-day review totals for the last N days
    #️ days with no activity are filled with zeroes so the frontend
    #️ always receives a contiguous series suitable for charting

    today = utc_today()
    start_date = today - timedelta(days=days - 1)

    #️ fetch only the rows that exist in the date window
    rows = await DailyActivity.filter(
        user_id=user.id,
        date__gte=start_date,
        date__lte=today,
    ).order_by("date")

    #️ index by date for O(1) lookup while filling gaps
    activity_by_date: dict[date, DailyActivity] = {r.date: r for r in rows}

    #️ build the full contiguous list, inserting zeroes for missing days
    result: list[DailyActivityOut] = []
    for offset in range(days):
        d = start_date + timedelta(days=offset)
        act = activity_by_date.get(d)
        result.append(
            DailyActivityOut(
                date=d,
                cards_reviewed=act.cards_reviewed if act else 0,
                cards_correct=act.cards_correct if act else 0,
            )
        )

    return result


#️
#️ 2. Total Stats Endpoint
#️

@router.get("/total", response_model=TotalStatsOut)
async def get_total_stats(
    user: User = Depends(get_current_user),
):
    #️ returns lifetime totals and the current study-day streak
    #️ totals come from ReviewEvent (the source of truth)
    #️ streak counts consecutive days ending today or yesterday

    #️ pull all review events for this user
    events = await ReviewEvent.filter(user_id=user.id).all()

    total_reviewed = len(events)
    total_correct = sum(1 for e in events if e.correct)

    #️ compute accuracy percentage, default to 0.0 if no reviews
    if total_reviewed > 0:
        accuracy_pct = round((total_correct / total_reviewed) * 100, 1)
    else:
        accuracy_pct = 0.0

    #️ compute the current streak from DailyActivity
    streak = await _compute_streak(user.id)

    return TotalStatsOut(
        total_cards_reviewed=total_reviewed,
        overall_accuracy_pct=accuracy_pct,
        current_streak_days=streak,
    )


#️
#️ 3. Streak Helper
#️

async def _compute_streak(user_id: int) -> int:
    #️ walks backwards from today (or yesterday) counting consecutive
    #️ days with at least one card reviewed

    today = utc_today()

    #️ pull all active days ordered newest-first
    rows = (
        await DailyActivity.filter(user_id=user_id, cards_reviewed__gt=0)
        .order_by("-date")
        .all()
    )

    if not rows:
        return 0

    active_dates: set[date] = {r.date for r in rows}

    #️ the streak can start from today or yesterday
    #️ (user may not have studied yet today but still has an active streak)
    if today in active_dates:
        check = today
    elif (today - timedelta(days=1)) in active_dates:
        check = today - timedelta(days=1)
    else:
        return 0

    #️ count consecutive active days going backwards
    streak = 0
    while check in active_dates:
        streak += 1
        check -= timedelta(days=1)

    return streak
