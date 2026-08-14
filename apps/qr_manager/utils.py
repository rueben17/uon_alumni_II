from django.utils import timezone


def humanize_duration(start, end):
    """
    Single largest whole unit elapsed from ``start`` to ``end``, floored,
    as a human-readable string:

    - ``end``'s calendar date on or before ``start``'s (same day, clock
      skew, or a future-dated ``start``): "Today" -- never negative.
    - Under 30 days: "N day" / "N days"
    - Under 12 whole months: "N month" / "N months"
    - 12 whole months or more: "N year" / "N years"

    Months/years are calendar-aware -- computed from year/month/day
    components and decremented if ``end``'s day-of-month is earlier than
    ``start``'s, not by dividing elapsed days by 30 or 365. A Feb 29
    ``start`` compared against Feb 28 the following (non-leap) year
    therefore reads as 11 months, not a full year, since the 29th
    hasn't recurred yet.

    Both datetimes are converted to local time (Africa/Nairobi) via
    timezone.localtime() when aware, so a UTC-midnight boundary can't
    shift which calendar day either one falls on.
    """
    if timezone.is_aware(start):
        start = timezone.localtime(start)
    if timezone.is_aware(end):
        end = timezone.localtime(end)

    if end.date() <= start.date():
        return "Today"

    delta_days = (end.date() - start.date()).days
    if delta_days < 30:
        return f"{delta_days} day" if delta_days == 1 else f"{delta_days} days"

    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1

    if months < 12:
        return f"{months} month" if months == 1 else f"{months} months"

    years = months // 12
    return f"{years} year" if years == 1 else f"{years} years"
