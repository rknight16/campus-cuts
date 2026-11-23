"""Money formatting shared by services (error messages) and templates (|money filter)."""
from decimal import Decimal


def format_money(value):
    """Decimal("15000") -> "$15,000"; Decimal("400.50") -> "$400.50"; None -> "-"."""
    if value is None:
        return "-"
    value = Decimal(value)
    if value == value.to_integral_value():
        return f"${value:,.0f}"
    return f"${value:,.2f}"
