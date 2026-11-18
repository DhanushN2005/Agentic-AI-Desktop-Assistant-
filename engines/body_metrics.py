WEIGHT_RANGE_KG = (20.0, 500.0)
HEIGHT_RANGE_CM = (50.0, 272.0)
AGE_RANGE = (1, 120)
DURATION_RANGE_MIN = (1, 1440)


def check_ranges(weight_kg=None, height_cm=None, age=None, minutes=None):
    """Friendly error text when a value is implausible, else None."""
    if weight_kg is not None and not WEIGHT_RANGE_KG[0] <= weight_kg <= WEIGHT_RANGE_KG[1]:
        return (f"A weight of {weight_kg:g} kg doesn't look right. "
                f"I expect between {WEIGHT_RANGE_KG[0]:g} and {WEIGHT_RANGE_KG[1]:g} kg.")
    if height_cm is not None and not HEIGHT_RANGE_CM[0] <= height_cm <= HEIGHT_RANGE_CM[1]:
        return (f"A height of {height_cm:g} cm doesn't look right. "
                f"I expect between {HEIGHT_RANGE_CM[0]:g} and {HEIGHT_RANGE_CM[1]:g} cm.")
    if age is not None and not AGE_RANGE[0] <= age <= AGE_RANGE[1]:
        return f"An age of {age} doesn't look right. I expect {AGE_RANGE[0]} to {AGE_RANGE[1]} years."
    if minutes is not None and not DURATION_RANGE_MIN[0] <= minutes <= DURATION_RANGE_MIN[1]:
        return f"{minutes} minutes doesn't look right. I expect 1 to 1440 minutes."
    return None


class BodyMetricsEngine:
    """Body metrics calculator — BMI, calories, etc. No API needed."""

    MET_VALUES = {
        "walking": 3.5, "running": 9.8, "cycling": 7.5, "swimming": 8.0,
        "yoga": 3.0, "dancing": 5.5, "jumping rope": 12.3, "weight lifting": 5.0,
        "hiking": 6.0, "rowing": 7.0, "elliptical": 5.0, "stretching": 2.5,
        "gardening": 4.0, "cooking": 2.0, "cleaning": 3.3, "sitting": 1.5,
        "sleeping": 0.9, "standing": 2.0, "jogging": 7.0, "sports": 8.0,
    }

    def bmi(self, weight_kg: float, height_cm: float) -> str:
        if height_cm <= 0 or weight_kg <= 0:
            return "Weight and height must be positive."
        err = check_ranges(weight_kg=weight_kg, height_cm=height_cm)
        if err:
            return err
        height_m = height_cm / 100
        bmi_val = weight_kg / (height_m ** 2)
        if bmi_val < 18.5:
            category = "Underweight"
        elif bmi_val < 25:
            category = "Normal weight"
        elif bmi_val < 30:
            category = "Overweight"
        else:
            category = "Obese"
        return f"BMI: {bmi_val:.1f} ({category}). Healthy range: 18.5-24.9"

    def bmi_imperial(self, weight_lbs: float, height_inches: float) -> str:
        if height_inches <= 0 or weight_lbs <= 0:
            return "Weight and height must be positive."
        err = check_ranges(weight_kg=weight_lbs * 0.45359237, height_cm=height_inches * 2.54)
        if err:
            return err
        bmi_val = (weight_lbs / (height_inches ** 2)) * 703
        if bmi_val < 18.5:
            category = "Underweight"
        elif bmi_val < 25:
            category = "Normal weight"
        elif bmi_val < 30:
            category = "Overweight"
        else:
            category = "Obese"
        return f"BMI: {bmi_val:.1f} ({category}). Healthy range: 18.5-24.9"

    def bmr(self, weight_kg: float, height_cm: float, age: int, gender: str = "male") -> str:
        err = check_ranges(weight_kg=weight_kg, height_cm=height_cm, age=age)
        if err:
            return err
        if gender.lower() in ("m", "male"):
            bmr_val = 88.362 + (13.397 * weight_kg) + (4.799 * height_cm) - (5.677 * age)
        else:
            bmr_val = 447.593 + (9.247 * weight_kg) + (3.098 * height_cm) - (4.330 * age)
        tdee_light = bmr_val * 1.375
        tdee_moderate = bmr_val * 1.55
        tdee_active = bmr_val * 1.725
        return (f"BMR: {bmr_val:.0f} calories/day. "
                f"TDEE (light activity): {tdee_light:.0f}. "
                f"Moderate: {tdee_moderate:.0f}. "
                f"Active: {tdee_active:.0f}")

    def ideal_weight(self, height_cm: float, gender: str = "male") -> str:
        if height_cm <= 0:
            return "Height must be positive."
        err = check_ranges(height_cm=height_cm)
        if err:
            return err
        height_in = height_cm / 2.54
        if gender.lower() in ("m", "male"):
            ideal = 50 + 2.3 * (height_in - 60)
        else:
            ideal = 45.5 + 2.3 * (height_in - 60)
        if ideal <= 0:
            return "The ideal-weight formula only applies to adult heights (about 150 cm or taller)."
        return f"Ideal weight: {ideal:.1f} kg ({ideal * 2.205:.1f} lbs)"

    def calories_burned(self, activity: str, weight_kg: float, duration_min: int) -> str:
        err = check_ranges(weight_kg=weight_kg, minutes=duration_min)
        if err:
            return err
        met_values = self.MET_VALUES
        met = met_values.get(activity.lower(), 3.0)
        calories = met * weight_kg * (duration_min / 60)
        return f"{activity.title()} for {duration_min} min: {calories:.0f} calories burned (MET: {met})"
