from datetime import datetime, timedelta


class AgeCalculatorEngine:
    """Age and date calculator — no API needed."""

    def age(self, birthdate: str, fmt: str = "%Y-%m-%d") -> str:
        try:
            born = datetime.strptime(birthdate, fmt)
            today = datetime.now()
            years = today.year - born.year
            months = today.month - born.month
            days = today.day - born.day
            if days < 0:
                months -= 1
                days += 30
            if months < 0:
                years -= 1
                months += 12
            total_days = (today - born).days
            total_weeks = total_days // 7
            total_hours = total_days * 24
            return (f"Age: {years} years, {months} months, {days} days. "
                    f"That's {total_days:,} days, {total_weeks:,} weeks, or {total_hours:,} hours.")
        except ValueError:
            return f"Invalid date format. Use {fmt} (e.g., 1990-05-15)."

    def age_from_parts(self, year: int, month: int, day: int) -> str:
        try:
            born = datetime(year, month, day)
            today = datetime.now()
            years = today.year - born.year
            months = today.month - born.month
            days = today.day - born.day
            if days < 0:
                months -= 1
                days += 30
            if months < 0:
                years -= 1
                months += 12
            total_days = (today - born).days
            return (f"Age: {years} years, {months} months, {days} days. "
                    f"That's {total_days:,} days.")
        except ValueError:
            return "Invalid date."

    def days_between(self, date1: str, date2: str, fmt: str = "%Y-%m-%d") -> str:
        try:
            d1 = datetime.strptime(date1, fmt)
            d2 = datetime.strptime(date2, fmt)
            diff = abs((d2 - d1).days)
            weeks = diff // 7
            months = diff // 30
            return f"Days between: {diff} days ({weeks} weeks, ~{months} months)"
        except ValueError:
            return f"Invalid date format. Use {fmt}."

    def add_days(self, date: str, days: int, fmt: str = "%Y-%m-%d") -> str:
        try:
            d = datetime.strptime(date, fmt)
            result = d + timedelta(days=days)
            return f"{date} + {days} days = {result.strftime(fmt)}"
        except ValueError:
            return f"Invalid date format. Use {fmt}."

    def subtract_days(self, date: str, days: int, fmt: str = "%Y-%m-%d") -> str:
        try:
            d = datetime.strptime(date, fmt)
            result = d - timedelta(days=days)
            return f"{date} - {days} days = {result.strftime(fmt)}"
        except ValueError:
            return f"Invalid date format. Use {fmt}."

    def next_birthday(self, birthdate: str, fmt: str = "%Y-%m-%d") -> str:
        try:
            born = datetime.strptime(birthdate, fmt)
            today = datetime.now()
            this_year_bday = born.replace(year=today.year)
            if this_year_bday < today:
                next_bday = born.replace(year=today.year + 1)
            else:
                next_bday = this_year_bday
            days_until = (next_bday - today).days
            age_next = next_bday.year - born.year
            return f"Next birthday: {next_bday.strftime('%B %d, %Y')}. {days_until} days away. You'll be {age_next}."
        except ValueError:
            return f"Invalid date format. Use {fmt}."

    def zodiac(self, birthdate: str, fmt: str = "%Y-%m-%d") -> str:
        try:
            born = datetime.strptime(birthdate, fmt)
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
        except ValueError:
            return f"Invalid date format. Use {fmt}."
