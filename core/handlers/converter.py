import re

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
    "lb": 0.45359237, "lbs": 0.45359237, "pound": 0.45359237, "poundmass": 0.45359237,
    "tonne": 1000.0, "tonnes": 1000.0, "metric ton": 1000.0, "metric tons": 1000.0,
    "stone": 6.35029318, "stones": 6.35029318,
    "oz": 0.028349523125, "ounce": 0.028349523125, "ounces": 0.028349523125,
}

_DATA_MB = {
    "b": 1e-6, "byte": 1e-6, "bytes": 1e-6,
    "kb": 0.001, "kilobyte": 0.001, "kilobytes": 0.001,
    "mb": 1.0, "megabyte": 1.0, "megabytes": 1.0,
    "gb": 1024.0, "gigabyte": 1024.0, "gigabytes": 1024.0,
    "tb": 1048576.0, "terabyte": 1048576.0, "terabytes": 1048576.0,
}


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


def handle_convert(orch, c):
    text = c.lower().strip()
    m = re.search(r"convert\s+(?:the\s+)?([\d.,]+)\s*([a-z]+(?: [a-z]+)?)\s+(?:to|into|in)\s+([a-z]+(?: [a-z]+)?)\s*$", text)
    if not m:
        orch.speak("Say something like 'convert 100 dollars to rupees' or 'convert 5 kilometers to miles'.")
        return True
    try:
        value = float(m.group(1).replace(",", ""))
    except ValueError:
        orch.speak("I couldn't read the number to convert.")
        return True
    src, dst = m.group(2), m.group(3)

    if src in _TEMP and dst in _TEMP:
        celsius = _to_temp(value, _TEMP[src])
        if celsius is None:
            orch.speak("I couldn't do that temperature conversion.")
            return True
        result = _from_temp(celsius, _TEMP[dst])
        orch.speak(f"{value} {src} is {result:,.2f} {dst}.")
        return True

    for table in (_LENGTH_M, _WEIGHT_KG, _DATA_MB):
        if src in table and dst in table:
            result = value * table[src] / table[dst]
            orch.speak(f"{value} {src} is {result:,.2f} {dst}.")
            return True

    if src in _CURRENCY_USD and dst in _CURRENCY_USD:
        result = value * _CURRENCY_USD[src] / _CURRENCY_USD[dst]
        orch.speak(f"{value} {src} is about {result:,.2f} {dst}.")
        return True

    orch.speak(f"I can convert {src} to {dst}, but I don't know that pair.")
    return True
