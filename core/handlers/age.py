import re
from datetime import datetime


def handle_age(orch, c):
    """Handle age and date calculation commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    cmd = c.lower().strip()
    cmd = re.sub(r"^(flexi|flexie|hey flexie|ok flexie)\b", "", cmd).strip()

    # Find date patterns (YYYY-MM-DD, DD/MM/YYYY, etc.)
    date_pattern = r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})"
    dates = re.findall(date_pattern, cmd)

    # Also try DD-MM-YYYY
    if not dates:
        date_pattern2 = r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})"
        dates2 = re.findall(date_pattern2, cmd)
        if dates2:
            dates = [(d[2], d[1], d[0]) for d in dates2]

    if "zodiac" in cmd or "star sign" in cmd or "horoscope" in cmd:
        if dates:
            y, m, d = dates[0]
            response = orch.age_calc.zodiac(f"{y}-{int(m):02d}-{int(d):02d}")
        else:
            response = "Provide a birthdate. Say 'zodiac 1990-05-15'."
    elif "days between" in cmd or "difference" in cmd:
        if len(dates) >= 2:
            d1 = f"{dates[0][0]}-{int(dates[0][1]):02d}-{int(dates[0][2]):02d}"
            d2 = f"{dates[1][0]}-{int(dates[1][1]):02d}-{int(dates[1][2]):02d}"
            response = orch.age_calc.days_between(d1, d2)
        else:
            response = "Provide two dates. Say 'days between 2020-01-01 and 2025-12-31'."
    elif "add" in cmd and "day" in cmd:
        if dates:
            date_str = f"{dates[0][0]}-{int(dates[0][1]):02d}-{int(dates[0][2]):02d}"
            num_match = re.search(r"add\s+(\d+)", cmd)
            days = int(num_match.group(1)) if num_match else 1
            response = orch.age_calc.add_days(date_str, days)
        else:
            response = "Provide a date and days. Say 'add 10 days to 2025-01-01'."
    elif "subtract" in cmd and "day" in cmd:
        if dates:
            date_str = f"{dates[0][0]}-{int(dates[0][1]):02d}-{int(dates[0][2]):02d}"
            num_match = re.search(r"subtract\s+(\d+)", cmd)
            days = int(num_match.group(1)) if num_match else 1
            response = orch.age_calc.subtract_days(date_str, days)
        else:
            response = "Provide a date and days. Say 'subtract 10 days from 2025-01-01'."
    elif "next birthday" in cmd or "birthday" in cmd:
        if dates:
            date_str = f"{dates[0][0]}-{int(dates[0][1]):02d}-{int(dates[0][2]):02d}"
            response = orch.age_calc.next_birthday(date_str)
        else:
            response = "Provide a birthdate. Say 'next birthday 1990-05-15'."
    else:
        if dates:
            date_str = f"{dates[0][0]}-{int(dates[0][1]):02d}-{int(dates[0][2]):02d}"
            response = orch.age_calc.age(date_str)
        else:
            response = "Provide a birthdate. Say 'age 1990-05-15' or 'next birthday 1990-05-15'."

    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True
