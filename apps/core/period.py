from datetime import datetime, timedelta

from django.utils import timezone

PERIOD_CHOICES = [
    ("today", "Today"),
    ("yesterday", "Yesterday"),
    ("this_week", "This Week"),
    ("last_week", "Last Week"),
    ("this_month", "This Month"),
    ("last_month", "Last Month"),
    ("this_year", "This Year"),
    ("custom", "Custom Range"),
]


def parse_period(period, request):
    today = timezone.localdate()
    if period == "today":
        start, end = today, today + timedelta(days=1)
    elif period == "yesterday":
        start, end = today - timedelta(days=1), today
    elif period == "this_week":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=7)
    elif period == "last_week":
        this_week_start = today - timedelta(days=today.weekday())
        start = this_week_start - timedelta(days=7)
        end = this_week_start
    elif period == "last_month":
        first_this = today.replace(day=1)
        last_month_end = first_this - timedelta(days=1)
        start = last_month_end.replace(day=1)
        end = first_this
    elif period == "this_year":
        start = today.replace(month=1, day=1)
        try:
            end = today.replace(year=today.year + 1, month=1, day=1)
        except ValueError:
            end = today.replace(month=1, day=1) + timedelta(days=365)
    elif period == "custom":
        raw_start = request.GET.get("start", "")
        raw_end = request.GET.get("end", "")
        try:
            start = (
                datetime.strptime(raw_start, "%Y-%m-%d").date()
                if raw_start
                else today.replace(day=1)
            )
        except ValueError:
            start = today.replace(day=1)
        try:
            end = (
                datetime.strptime(raw_end, "%Y-%m-%d").date() + timedelta(days=1)
                if raw_end
                else today + timedelta(days=1)
            )
        except ValueError:
            end = today + timedelta(days=1)
    else:
        first_this = today.replace(day=1)
        if today.month == 12:
            next_month = today.replace(year=today.year + 1, month=1, day=1)
        else:
            next_month = today.replace(month=today.month + 1, day=1)
        start, end = first_this, next_month
    tz = timezone.get_current_timezone()
    start_dt = timezone.make_aware(datetime.combine(start, datetime.min.time()), tz)
    end_dt = timezone.make_aware(datetime.combine(end, datetime.min.time()), tz)
    return start_dt, end_dt


def parse_period_from_request(request, default="this_month"):
    period = request.GET.get("period", default) or default
    if period not in dict(PERIOD_CHOICES):
        period = default
    start, end = parse_period(period, request)
    return period, start, end
