class TipCalculatorEngine:
    """Tip and bill splitting calculator — no API needed."""

    def calculate(self, bill: float, tip_percent: float = 15.0, split: int = 1) -> str:
        tip_amount = bill * (tip_percent / 100)
        total = bill + tip_amount
        per_person = total / split if split > 0 else total

        parts = [
            f"Bill: ${bill:.2f}",
            f"Tip ({tip_percent:.0f}%): ${tip_amount:.2f}",
            f"Total: ${total:.2f}",
        ]
        if split > 1:
            parts.append(f"Split {split} ways: ${per_person:.2f} each")
        return ". ".join(parts)

    def split_bill(self, bill: float, people: int, tip_percent: float = 15.0) -> str:
        if people <= 0:
            return "Number of people must be at least 1."
        tip_amount = bill * (tip_percent / 100)
        total = bill + tip_amount
        per_person = total / people
        return f"Bill: ${bill:.2f}. Tip ({tip_percent:.0f}%): ${tip_amount:.2f}. Total: ${total:.2f}. Each person pays: ${per_person:.2f}"

    def tip_from_total(self, total: float, bill: float) -> str:
        if bill <= 0:
            return "Bill must be greater than 0."
        tip_amount = total - bill
        tip_percent = (tip_amount / bill) * 100
        return f"Tip amount: ${tip_amount:.2f} ({tip_percent:.1f}% of bill)"
