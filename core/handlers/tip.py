import re


def handle_tip(orch, c):
    """Handle tip calculation commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    cmd = c.lower().strip()
    cmd = re.sub(r"^(flexi|flexie|hey flexie|ok flexie)\b", "", cmd).strip()

    # Extract numbers
    numbers = re.findall(r"\d+\.?\d*", cmd)
    tip_match = re.search(r"(\d+)%?\s*tip", cmd)
    split_match = re.search(r"(?:split|share|divide)\s*(?:by|among|between)?\s*(\d+)", cmd)
    bill_match = re.search(r"\$?(\d+\.?\d*)", cmd)

    tip_percent = float(tip_match.group(1)) if tip_match else 15.0
    split = int(split_match.group(1)) if split_match else 1

    if "from total" in cmd or "what percent" in cmd:
        if len(numbers) >= 2:
            response = orch.tip_calc.tip_from_total(float(numbers[0]), float(numbers[1]))
        else:
            response = "Provide total and bill amount."
    elif bill_match:
        bill = float(bill_match.group(1))
        response = orch.tip_calc.calculate(bill, tip_percent, split)
    elif len(numbers) >= 1:
        bill = float(numbers[0])
        response = orch.tip_calc.calculate(bill, tip_percent, split)
    else:
        response = "Provide a bill amount. Say 'tip 20% on $50' or 'split $60 by 3'."

    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True
