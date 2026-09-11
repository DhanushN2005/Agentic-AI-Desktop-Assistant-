class BodyMetricsEngine:
    """Body metrics calculator — BMI, calories, etc. No API needed."""

    def bmi(self, weight_kg: float, height_cm: float) -> str:
        if height_cm <= 0 or weight_kg <= 0:
            return "Weight and height must be positive."
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
        height_in = height_cm / 2.54
        if gender.lower() in ("m", "male"):
            ideal = 50 + 2.3 * (height_in - 60)
        else:
            ideal = 45.5 + 2.3 * (height_in - 60)
        return f"Ideal weight: {ideal:.1f} kg ({ideal * 2.205:.1f} lbs)"

    def calories_burned(self, activity: str, weight_kg: float, duration_min: int) -> str:
        met_values = {
            "walking": 3.5, "running": 9.8, "cycling": 7.5, "swimming": 8.0,
            "yoga": 3.0, "dancing": 5.5, "jumping rope": 12.3, "weight lifting": 5.0,
            "hiking": 6.0, "rowing": 7.0, "elliptical": 5.0, "stretching": 2.5,
            "gardening": 4.0, "cooking": 2.0, "cleaning": 3.3, "sitting": 1.5,
            "sleeping": 0.9, "standing": 2.0, "jogging": 7.0, "sports": 8.0,
        }
        met = met_values.get(activity.lower(), 3.0)
        calories = met * weight_kg * (duration_min / 60)
        return f"{activity.title()} for {duration_min} min: {calories:.0f} calories burned (MET: {met})"
