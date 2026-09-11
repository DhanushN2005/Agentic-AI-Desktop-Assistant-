import re


def handle_body_metrics(orch, c):
    """Handle body metrics commands (BMI, calories, etc.)."""
    orch.send_to_ui("STATE", "PROCESSING")
    cmd = c.lower().strip()
    cmd = re.sub(r"^(flexi|flexie|hey flexie|ok flexie)\b", "", cmd).strip()

    numbers = re.findall(r"\d+\.?\d*", cmd)
    is_imperial = any(x in cmd for x in ["lbs", "pounds", "inches", "ft", "feet"])
    gender = "female" if any(x in cmd for x in ["female", "woman", "girl", "she"]) else "male"

    if "bmi" in cmd:
        if len(numbers) >= 2:
            if is_imperial:
                response = orch.body_metrics.bmi_imperial(float(numbers[0]), float(numbers[1]))
            else:
                response = orch.body_metrics.bmi(float(numbers[0]), float(numbers[1]))
        else:
            response = "Provide weight and height. Say 'BMI 70 kg 175 cm' or 'BMI 150 lbs 70 inches'."
    elif "bmr" in cmd or "metabolic" in cmd:
        if len(numbers) >= 3:
            response = orch.body_metrics.bmr(float(numbers[0]), float(numbers[1]), int(float(numbers[2])), gender)
        else:
            response = "Provide weight (kg), height (cm), and age. Say 'BMR 70 175 25'."
    elif "ideal weight" in cmd:
        if numbers:
            response = orch.body_metrics.ideal_weight(float(numbers[0]), gender)
        else:
            response = "Provide height in cm. Say 'ideal weight 175'."
    elif "calorie" in cmd or "burn" in cmd:
        activity = None
        for a in ["walking", "running", "cycling", "swimming", "yoga", "dancing",
                   "jumping rope", "weight lifting", "hiking", "rowing", "jogging",
                   "sports", "cleaning", "cooking", "sitting", "sleeping", "standing"]:
            if a in cmd:
                activity = a
                break
        if activity and len(numbers) >= 2:
            response = orch.body_metrics.calories_burned(activity, float(numbers[0]), int(float(numbers[1])))
        else:
            response = "Say 'calories burned running 70kg 30 minutes'."
    else:
        if len(numbers) >= 2:
            response = orch.body_metrics.bmi(float(numbers[0]), float(numbers[1]))
        else:
            response = "Say 'BMI 70 175' or 'BMR 70 175 25' or 'calories burned running 70 30'."

    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True
