import json
import logging
import math
import os
import re

from utils.voice_parse import strip_wake

_CURRENCY_USD = {
    "usd": 1.0, "dollar": 1.0, "dollars": 1.0, "us": 1.0,
    "inr": 0.0116, "rupee": 0.0116, "rupees": 0.0116, "rs": 0.0116,
    "eur": 1.08, "euro": 1.08, "euros": 1.08,
    "gbp": 1.27, "pound": 1.27, "pounds": 1.27, "sterling": 1.27,
    "jpy": 0.0067, "yen": 0.0067,
    "cad": 0.73, "canadian dollar": 0.73,
    "aud": 0.66, "australian dollar": 0.66,
    "cny": 0.14, "yuan": 0.14,
}

_TEMP = {"celsius": "c", "centigrade": "c", "c": "c", "fahrenheit": "f", "f": "f", "kelvin": "k", "k": "k"}

_LENGTH_M = {
    "m": 1.0, "meter": 1.0, "meters": 1.0, "metre": 1.0, "metres": 1.0,
    "km": 1000.0, "kilometer": 1000.0, "kilometers": 1000.0, "kilometre": 1000.0, "kilometres": 1000.0,
    "cm": 0.01, "centimeter": 0.01, "centimeters": 0.01, "centimetre": 0.01, "centimetres": 0.01,
    "mm": 0.001, "millimeter": 0.001, "millimeters": 0.001,
    "mile": 1609.344, "miles": 1609.344,
    "yard": 0.9144, "yards": 0.9144,
    "foot": 0.3048, "feet": 0.3048, "ft": 0.3048,
    "inch": 0.0254, "inches": 0.0254, "in": 0.0254,
}

_WEIGHT_KG = {
    "kg": 1.0, "kilogram": 1.0, "kilograms": 1.0, "kilogramme": 1.0, "kilogrammes": 1.0,
    "g": 0.001, "gram": 0.001, "grams": 0.001, "gramme": 0.001, "grammes": 0.001,
    "mg": 1e-6, "milligram": 1e-6, "milligrams": 1e-6,
    "lb": 0.45359237, "lbs": 0.45359237, "pound": 0.45359237, "pounds": 0.45359237, "poundmass": 0.45359237,
    "tonne": 1000.0, "tonnes": 1000.0, "metric ton": 1000.0, "metric tons": 1000.0,
    "ton": 907.18474, "tons": 907.18474, "short ton": 907.18474, "short tons": 907.18474,
    "stone": 6.35029318, "stones": 6.35029318,
    "oz": 0.028349523125, "ounce": 0.028349523125, "ounces": 0.028349523125,
}

# Binary units (1 KB = 1024 bytes, as Windows reports sizes); base unit = byte.
_DATA_BINARY_NOTE = "binary units: 1 KB = 1024 bytes"
_DATA_BYTES = {
    "b": 1.0, "byte": 1.0, "bytes": 1.0,
    "kb": 1024.0, "kilobyte": 1024.0, "kilobytes": 1024.0,
    "mb": 1024.0 ** 2, "megabyte": 1024.0 ** 2, "megabytes": 1024.0 ** 2,
    "gb": 1024.0 ** 3, "gigabyte": 1024.0 ** 3, "gigabytes": 1024.0 ** 3,
    "tb": 1024.0 ** 4, "terabyte": 1024.0 ** 4, "terabytes": 1024.0 ** 4,
}
_DATA_MB = _DATA_BYTES  # backwards-compatible alias

_VOLUME_L = {
    "l": 1.0, "liter": 1.0, "liters": 1.0, "litre": 1.0, "litres": 1.0,
    "ml": 0.001, "milliliter": 0.001, "milliliters": 0.001, "millilitre": 0.001, "millilitres": 0.001,
    "gallon": 3.785411784, "gallons": 3.785411784,
    "quart": 0.946352946, "quarts": 0.946352946,
    "pint": 0.473176473, "pints": 0.473176473,
    "cup": 0.2365882365, "cups": 0.2365882365,
}

# Currency values are STATIC approximations, not live rates.
_RATES_AS_OF = "2025-01"
_RATES_ENV = "FLEXIE_CURRENCY_RATES"


def _currency_rates():
    """Built-in rates, overridden by a JSON file ({"inr": 0.0118, ...}) named by
    the FLEXIE_CURRENCY_RATES env var or data/currency_rates.json."""
    rates = dict(_CURRENCY_USD)
    path = os.environ.get(_RATES_ENV)
    if not path:
        try:
            from utils.config import Config
            base = getattr(Config, "DATA_DIR", None)
            if base:
                cand = os.path.join(base, "currency_rates.json")
                path = cand if os.path.exists(cand) else None
        except Exception:
            path = None
    if path:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.items():
                if isinstance(v, (int, float)) and v > 0:
                    rates[str(k).lower()] = float(v)
        except Exception as _e:
            logging.debug("[converter] bad currency rate file %s: %s", path, _e)
    return rates, bool(path)



def _to_temp(value, unit):
    unit = unit.lower()
    if unit == "c":
        return value
    if unit == "f":
        return (value - 32) * 5 / 9
    if unit == "k":
        return value - 273.15
    return None


def _from_temp(celsius, unit):
    unit = unit.lower()
    if unit == "c":
        return celsius
    if unit == "f":
        return celsius * 9 / 5 + 32
    if unit == "k":
        return celsius + 273.15
    return None


_USAGE = "Say something like 'convert 100 dollars to rupees' or 'convert 5 kilometers to miles'."

_CONVERT_RE = re.compile(
    r"convert\s+(?:the\s+)?(-?[\d][\d.,]*|-?\.\d+)\s*([a-z]+(?: [a-z]+)?)\s+(?:to|into|in)\s+([a-z]+(?: [a-z]+)?)\s*[?.!]*\s*$"
)


def _parse_number(tok: str):
    """'1,5' -> 1.5 (decimal comma), '1,500' -> 1500, '1.234,5' -> 1234.5."""
    neg = tok.startswith("-")
    t = tok.lstrip("-")
    if "," in t and "." in t:
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    elif "," in t:
        if re.fullmatch(r"\d{1,3}(?:,\d{3})+", t):
            t = t.replace(",", "")
        else:
            t = t.replace(",", ".") if t.count(",") == 1 else t.replace(",", "")
    elif t.count(".") > 1:
        t = t.replace(".", "")
    val = float(t)
    return -val if neg else val


def _norm_unit(u: str, tables) -> str | None:
    """Canonical key of u in any table (handles 'degrees celsius', plurals)."""
    u = u.strip().lower()
    u = re.sub(r"^degrees?\s+", "", u)
    cands = [u]
    if u.endswith("es"):
        cands.append(u[:-2])
    if u.endswith("s"):
        cands.append(u[:-1])
    for cand in cands:
        for table in tables:
            if cand in table:
                return cand
    return None


def _fmt(value: float) -> str:
    """Adaptive rounding: 1,234.57 for normal values, 3 significant digits when
    small so 0.000001 never prints as 0.00."""
    if value == 0:
        return "0"
    mag = abs(value)
    if mag >= 1:
        return f"{value:,.2f}"
    if mag >= 0.01:
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return f"{value:.3g}"


def handle_convert(orch, c):
    text = strip_wake(c).lower().replace("°", " ").strip()
    text = re.sub(r"\s+", " ", text)
    m = _CONVERT_RE.search(text)
    if not m:
        orch.speak(_USAGE)
        return True
    try:
        value = _parse_number(m.group(1))
    except ValueError as _e:
        logging.debug("[core/handlers/converter.py] bad number: %s: %s", type(_e).__name__, _e)
        orch.speak("I couldn't read the number to convert.")
        return True
    if not math.isfinite(value) or abs(value) > 1e18:
        orch.speak("That number is too large for me to convert.")
        return True
    src_raw, dst_raw = m.group(2), m.group(3)
    shown_val = f"{value:g}" if abs(value) < 1e15 else f"{value:.6g}"

    if (_norm_unit(src_raw, [_TEMP]) and _norm_unit(dst_raw, [_TEMP])
            and not re.fullmatch(r"degrees?", src_raw)):
        s_key = _TEMP[_norm_unit(src_raw, [_TEMP])]
        d_key = _TEMP[_norm_unit(dst_raw, [_TEMP])]
        celsius = _to_temp(value, s_key)
        if celsius is None or celsius < -273.15 - 1e-9:
            orch.speak("That is below absolute zero, so it isn't a real temperature.")
            return True
        result = _from_temp(celsius, d_key)
        orch.speak(f"{shown_val} {src_raw} is {_fmt(result)} {dst_raw}.")
        return True

    # Weight/length/data/volume tables; first table containing BOTH units wins
    # (so 'pounds to kg' is weight, 'pounds to dollars' falls through to currency).
    for table in (_LENGTH_M, _WEIGHT_KG, _DATA_BYTES, _VOLUME_L):
        s_key = _norm_unit(src_raw, [table])
        d_key = _norm_unit(dst_raw, [table])
        if s_key and d_key:
            result = value * table[s_key] / table[d_key]
            note = f" ({_DATA_BINARY_NOTE})" if table is _DATA_BYTES else ""
            orch.speak(f"{shown_val} {src_raw} is {_fmt(result)} {dst_raw}{note}.")
            return True

    rates, overridden = _currency_rates()
    s_key = _norm_unit(src_raw, [rates])
    d_key = _norm_unit(dst_raw, [rates])
    if s_key and d_key:
        result = value * rates[s_key] / rates[d_key]
        basis = "your configured rates" if overridden else f"fixed approximate rates as of {_RATES_AS_OF}, not live"
        orch.speak(f"{shown_val} {src_raw} is about {_fmt(result)} {dst_raw} ({basis}).")
        return True

    orch.speak(f"I can convert {src_raw} to {dst_raw}, but I don't know that pair.")
    return True
