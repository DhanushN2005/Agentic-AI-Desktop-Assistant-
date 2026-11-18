import re

from engines.body_metrics import BodyMetricsEngine
from utils.voice_parse import strip_wake

_NUM = r"(\d+(?:\.\d+)?)"
_KG = re.compile(_NUM + r"\s*(?:kgs?|kilograms?|kilos?)\b", re.IGNORECASE)
_LB = re.compile(_NUM + r"\s*(?:lbs?|pounds?)\b", re.IGNORECASE)
_CM = re.compile(_NUM + r"\s*(?:cm|centimet(?:er|re)s?)\b", re.IGNORECASE)
_M = re.compile(_NUM + r"\s*(?:m|met(?:er|re)s?)\b(?!\w)", re.IGNORECASE)
_FT_IN = re.compile(
    r"(?<![\w.])(\d+)\s*(?:ft|foot|feet|')\s*(?:(?P<inch>\d+(?:\.\d+)?)\s*(?:in|inch|inches|\")|"
    r"(?P<bare>\d{1,2})(?![\d.]|\s*(?:kg|kilo|lb|pound|cm|met|m\b|year|yr|yo|min|hour|hr|old)))?",
    re.IGNORECASE,
)
_IN = re.compile(_NUM + r"\s*(?:in|inch|inches)\b", re.IGNORECASE)
_AGE = [
    re.compile(r"\bage\s*(?:of\s*|is\s*)?(\d{1,3})\b", re.IGNORECASE),
    re.compile(r"\b(\d{1,3})\s*(?:years?|yrs?|yo|y/o)\b", re.IGNORECASE),
]
_MIN = re.compile(_NUM + r"\s*(?:min(?:ute)?s?)\b", re.IGNORECASE)
_HOUR = re.compile(_NUM + r"\s*(?:hours?|hrs?)\b", re.IGNORECASE)
LB_TO_KG = 0.45359237


def parse_measurements(text: str) -> dict:
    """Weight (kg), height (cm), age, minutes parsed with units from the original text."""
    out = {"weight_kg": None, "height_cm": None, "age": None, "minutes": None}
    work = text
    m = _KG.search(work)
    if m:
        out["weight_kg"] = float(m.group(1))
        work = work[:m.start()] + " " + work[m.end():]
    else:
        m = _LB.search(work)
        if m:
            out["weight_kg"] = float(m.group(1)) * LB_TO_KG
            work = work[:m.start()] + " " + work[m.end():]

    m = _CM.search(work)
    if m:
        out["height_cm"] = float(m.group(1))
        work = work[:m.start()] + " " + work[m.end():]
    else:
        m = _FT_IN.search(work)
        if m:
            extra = m.group("inch") or m.group("bare")
            inches = int(m.group(1)) * 12 + (float(extra) if extra else 0.0)
            out["height_cm"] = inches * 2.54
            work = work[:m.start()] + " " + work[m.end():]
        else:
            m = _IN.search(work)
            if m:
                out["height_cm"] = float(m.group(1)) * 2.54
                work = work[:m.start()] + " " + work[m.end():]
            else:
                m = _M.search(work)
                if m:
                    out["height_cm"] = float(m.group(1)) * 100
                    work = work[:m.start()] + " " + work[m.end():]

    for rx in _AGE:
        m = rx.search(work)
        if m:
            out["age"] = int(m.group(1))
            work = work[:m.start()] + " " + work[m.end():]
            break
    m = _MIN.search(work)
    if m:
        out["minutes"] = int(float(m.group(1)))
        work = work[:m.start()] + " " + work[m.end():]
    else:
        m = _HOUR.search(work)
        if m:
            out["minutes"] = int(float(m.group(1)) * 60)
            work = work[:m.start()] + " " + work[m.end():]
    out["leftover"] = [float(n) for n in re.findall(_NUM, work)]
    return out


def _fill_positional(p: dict, order: list):
    """Assign still-missing values from bare numbers, in the given key order."""
    left = list(p["leftover"])
    for key in order:
        if p[key] is None and left:
            p[key] = left.pop(0)
    # bare heights below 3 are metres ('1.75')
    if p["height_cm"] is not None and 0 < p["height_cm"] <= 3:
        p["height_cm"] *= 100


def handle_body_metrics(orch, c):
    """Handle body metrics commands (BMI, calories, etc.)."""
    orch.send_to_ui("STATE", "PROCESSING")
    original = strip_wake(c)
    cmd = original.lower()
    eng = getattr(orch, "body_metrics", None) or BodyMetricsEngine()

    p = parse_measurements(original)
    gender = "female" if re.search(r"\b(?:female|woman|girl|she|her)\b", cmd) else "male"

    if "bmi" in cmd:
        _fill_positional(p, ["weight_kg", "height_cm"])
        if p["weight_kg"] is not None and p["height_cm"] is not None:
            response = eng.bmi(p["weight_kg"], p["height_cm"])
        else:
            response = "Provide weight and height. Say 'BMI 70 kg 175 cm' or 'BMI 150 lbs 5 ft 10 in'."
    elif "bmr" in cmd or "metabolic" in cmd:
        _fill_positional(p, ["weight_kg", "height_cm", "age"])
        if None not in (p["weight_kg"], p["height_cm"], p["age"]):
            response = eng.bmr(p["weight_kg"], p["height_cm"], int(p["age"]), gender)
        else:
            response = "Provide weight, height, and age. Say 'BMR 70 kg 175 cm age 25'."
    elif "ideal weight" in cmd:
        _fill_positional(p, ["height_cm"])
        if p["height_cm"] is not None:
            response = eng.ideal_weight(p["height_cm"], gender)
        else:
            response = "Provide your height. Say 'ideal weight 175 cm' or 'ideal weight 5 ft 10 in'."
    elif "calorie" in cmd or re.search(r"\bburn", cmd):
        activity = None
        for a in sorted(eng.MET_VALUES, key=len, reverse=True):
            if re.search(rf"\b{re.escape(a)}\b", cmd):
                activity = a
                break
        _fill_positional(p, ["weight_kg", "minutes"])
        if activity and p["weight_kg"] is not None and p["minutes"] is not None:
            response = eng.calories_burned(activity, p["weight_kg"], int(p["minutes"]))
        else:
            response = "Say 'calories burned running 70kg 30 minutes'."
    else:
        _fill_positional(p, ["weight_kg", "height_cm"])
        if p["weight_kg"] is not None and p["height_cm"] is not None:
            response = eng.bmi(p["weight_kg"], p["height_cm"])
        else:
            response = "Say 'BMI 70 kg 175 cm' or 'BMR 70 kg 175 cm age 25' or 'calories burned running 70 kg 30 minutes'."

    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True
