"""UI helpers. {% load ui %} then:

    {% icon "cash" %}                 inline icon from rent/icon_sprite.html
    {% status_badge summary.status %} rent status pill (Paid, Partly paid, ...)
    {% percent paid owed as pct %}    whole-number percent, capped 0-100
"""
from decimal import Decimal

from django import template
from django.utils.html import format_html

from rent.services import rent_rules

register = template.Library()

# status -> (css modifier, icon)
STATUS_STYLES = {
    rent_rules.PAID: ("paid", "check"),
    rent_rules.PARTLY_PAID: ("partly", "half"),
    rent_rules.UNPAID: ("unpaid", "circle"),
    rent_rules.AWAITING_EARNINGS: ("awaiting", "clock"),
    "Overdue": ("overdue", "alert"),
    # Handoffs (US-03)
    "Awaiting confirmation": ("awaiting", "clock"),
    "Confirmed": ("paid", "check"),
    "Mismatch": ("overdue", "alert"),
}


@register.simple_tag
def icon(name):
    return format_html(
        '<svg class="icon" aria-hidden="true" focusable="false"><use href="#i-{}"/></svg>', name)


@register.simple_tag
def status_badge(status):
    modifier, glyph = STATUS_STYLES.get(status, ("unpaid", "circle"))
    return format_html('<span class="badge {}">{}{}</span>', modifier, icon(glyph), status)


@register.filter
def initials(name):
    """"Andre Campbell" -> "AC" (first and last word)."""
    words = str(name or "").split()
    if not words:
        return ""
    return (words[0][0] + (words[-1][0] if len(words) > 1 else "")).upper()


@register.simple_tag
def percent(part, whole):
    if not whole:
        return 0
    pct = Decimal(part or 0) / Decimal(whole) * 100
    return int(max(0, min(100, pct)))
