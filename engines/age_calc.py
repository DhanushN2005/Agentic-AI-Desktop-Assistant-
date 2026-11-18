import calendar
import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta


def _is_leap(year: int) -> bool:
    return calendar.isleap(year)


class AgeCalculatorEngine:
    """Age and date calculator — no API needed.

    All arithmetic is calendar-correct and done on dates (not datetimes), so
    'birthday tomorrow' is 1 day away regardless of the time of day.
    """

    def __init__(self, today: Callable[[], date] | date | None = None):
        self._today_src = today

    def _today(self) -> date:
        src = self._today_src
        if src is None:
            return date.today()
        return src() if callable(src) else src

    @staticmethod
    def _ymd(born: date, today: date) -> tuple[int, int, int]:
        """Whole years, months and days from born to today (calendar-correct).
        A Feb-29 birth date turns a year older on Mar 1 in non-leap years."""
        years = today.year - born.year
        months = today.month - born.month
        days = today.day - born.day
        if days < 0:
            months -= 1
            prev_year, prev_month = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
            days += calendar.monthrange(prev_year, prev_month)[1]
        if months < 0:
            years -= 1
            months += 12
        return years, months, days

    def _parse(self, s: str, fmt: str) -> date:
        return datetime.strptime(s, fmt).date()

    def age(self, birthdate: str, fmt: str = "%Y-%m-%d") -> str:
        try:
            born = self._parse(birthdate, fmt)
        except ValueError as _e:
            logging.debug("[engines/age_calc.py] Swallowed exception: %s: %s", type(_e).__name__, _e)
            return f"Invalid date format. Use {fmt} (e.g., 1990-05-15)."
        today = self._today()
        if born > today:
            return f"That birth date ({born.isoformat()}) is in the future. Please give a date in the past."
        years, months, days = self._ymd(born, today)
        total_days = (today - born).days
        total_weeks = total_days // 7
        total_hours = total_days * 24
        return (f"Age: {years} years, {months} months, {days} days. "
                f"That's {total_days:,} days, {total_weeks:,} weeks, or {total_hours:,} hours.")

    def age_from_parts(self, year: int, month: int, day: int) -> str:
        try:
            born = date(year, month, day)
        except (ValueError, TypeError) as _e:
            logging.debug("[engines/age_calc.py] Swallowed exception: %s: %s", type(_e).__name__, _e)
            return "Invalid date."
        today = self._today()
        if born > today:
            return f"That birth date ({born.isoformat()}) is in the future. Please give a date in the past."
        years, months, days = self._ymd(born, today)
        total_days = (today - born).days
        return (f"Age: {years} years, {months} months, {days} days. "
                f"That's {total_days:,} days.")

    def days_between(self, date1: str, date2: str, fmt: str = "%Y-%m-%d") -> str:
        try:
            d1 = self._parse(date1, fmt)
            d2 = self._parse(date2, fmt)
        except ValueError as _e:
            logging.debug("[engines/age_calc.py] Swallowed exception: %s: %s", type(_e).__name__, _e)
            return f"Invalid date format. Use {fmt}."
        diff = abs((d2 - d1).days)
        weeks = diff // 7
        lo, hi = (d1, d2) if d1 <= d2 else (d2, d1)
        y, m, d = self._ymd(lo, hi)
        months = y * 12 + m
        return f"Days between: {diff} days ({weeks} weeks, {months} months and {d} days)"

    def add_days(self, date_str: str, days: int, fmt: str = "%Y-%m-%d") -> str:
        try:
            d = self._parse(date_str, fmt)
            result = d + timedelta(days=days)
            return f"{date_str} + {days} days = {result.strftime(fmt)}"
        except ValueError as _e:
            logging.debug("[engines/age_calc.py] Swallowed exception: %s: %s", type(_e).__name__, _e)
            return f"Invalid date format. Use {fmt}."
        except OverflowError:
            return "That result is outside the range of dates I can handle."

    def subtract_days(self, date_str: str, days: int, fmt: str = "%Y-%m-%d") -> str:
        try:
            d = self._parse(date_str, fmt)
            result = d - timedelta(days=days)
            return f"{date_str} - {days} days = {result.strftime(fmt)}"
        except ValueError as _e:
            logging.debug("[engines/age_calc.py] Swallowed exception: %s: %s", type(_e).__name__, _e)
            return f"Invalid date format. Use {fmt}."
        except OverflowError:
            return "That result is outside the range of dates I can handle."

    @staticmethod
    def _anniversary(born: date, year: int) -> tuple[date, bool]:
        """Birthday in `year`; Feb 29 falls on Feb 28 in non-leap years."""
        if born.month == 2 and born.day == 29 and not _is_leap(year):
            return date(year, 2, 28), True
        return date(year, born.month, born.day), False

    def next_birthday(self, birthdate: str, fmt: str = "%Y-%m-%d") -> str:
        try:
            born = self._parse(birthdate, fmt)
        except ValueError as _e:
            logging.debug("[engines/age_calc.py] Swallowed exception: %s: %s", type(_e).__name__, _e)
            return f"Invalid date format. Use {fmt}."
        today = self._today()
        if born > today:
            return f"That birth date ({born.isoformat()}) is in the future. Please give a date in the past."
        this_year, moved = self._anniversary(born, today.year)
        if this_year < today:
            nxt, moved = self._anniversary(born, today.year + 1)
        else:
            nxt = this_year
        days_until = (nxt - today).days
        age_next = nxt.year - born.year
        note = (" (Feb 29 birthdays are counted as Feb 28 in non-leap years.)" if moved else "")
        if days_until == 0:
            return f"Your birthday is today, {nxt.strftime('%B %d, %Y')}! You turn {age_next} today.{note}"
        unit = "day" if days_until == 1 else "days"
        return (f"Next birthday: {nxt.strftime('%B %d, %Y')}. {days_until} {unit} away. "
                f"You'll be {age_next}.{note}")

    def zodiac(self, birthdate: str, fmt: str = "%Y-%m-%d") -> str:
        try:
            born = self._parse(birthdate, fmt)
            signs = [
                ((1, 20), (2, 18), "Aquarius", "The Water Bearer"),
                ((2, 19), (3, 20), "Pisces", "The Fish"),
                ((3, 21), (4, 19), "Aries", "The Ram"),
                ((4, 20), (5, 20), "Taurus", "The Bull"),
                ((5, 21), (6, 20), "Gemini", "The Twins"),
                ((6, 21), (7, 22), "Cancer", "The Crab"),
                ((7, 23), (8, 22), "Leo", "The Lion"),
                ((8, 23), (9, 22), "Virgo", "The Virgin"),
                ((9, 23), (10, 22), "Libra", "The Scales"),
                ((10, 23), (11, 21), "Scorpio", "The Scorpion"),
                ((11, 22), (12, 21), "Sagittarius", "The Archer"),
                ((12, 22), (1, 19), "Capricorn", "The Sea-Goat"),
            ]
            month, day = born.month, born.day
            for (sm, sd), (em, ed), name, symbol in signs:
                if (month == sm and day >= sd) or (month == em and day <= ed):
                    return f"Zodiac: {name} ({symbol})"
            return "Zodiac: Capricorn (The Sea-Goat)"
        except ValueError as _e:
            logging.debug("[engines/age_calc.py] Swallowed exception: %s: %s", type(_e).__name__, _e)
            return f"Invalid date format. Use {fmt}."
