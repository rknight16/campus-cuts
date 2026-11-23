"""{% load money %} then {{ amount|money }} gives "$15,000" (or "-" for None)."""
from django import template

from rent.formatting import format_money

register = template.Library()


@register.filter
def money(value):
    return format_money(value)
