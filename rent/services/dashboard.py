"""DashboardService (US-04) - owner: Dylandre Henry

Read-only summary for the Owner and Company Supervisor. Uses rent_rules for
owed/paid/balance/overdue per shop and lists each shop's handoff status.
Every shop is listed, even with $0 paid (AC-4).
"""
from django.utils import timezone

from rent.models import Handoff, HandoffStep, RentPeriod, Shop
from rent.services import rent_rules
ZERO = rent_rules.ZERO

def shop_summary(today=None):
    """One row per shop for the current rent period, plus totals for all shops."""
    if today is None:
        today = timezone.localdate()
    period = RentPeriod.for_date (today)
    handoffs = { h.shop_id: h
    for h in Handoff.objects.filter(step=HandoffStep.SHOP_TO_COMPANY, rent_period=period)}


    rows = []
    for shop in Shop.objects.select_related("supervisor"):
        owed = paid = balance = overdue = ZERO
        awaiting_earnings = 0
        for contractor in shop.contractors.filter(is_active=True):
            week = rent_rules.summary(contractor, period)
            paid += week["paid"]
            if week["owed"] is None:
                awaiting_earnings += 1   # commission, earnings not entered yet
            else:
                owed += week["owed"]
                balance += week["balance"]
            overdue += sum(
                (owing for _, owing in rent_rules.overdue_periods(contractor, today)), ZERO)
        rows.append({
            "shop": shop,
            "owed": owed,
            "paid": paid,
            "balance": balance,
            "overdue": overdue,
            "awaiting_earnings": awaiting_earnings,
            "handoff": handoffs.get(shop.pk),   # None means "not yet handed over"
        })

    totals = {key: sum((r[key] for r in rows), ZERO) for key in ("owed", "paid", "balance", "overdue")}
    return {"period": period, "shops": rows, "totals": totals}





    
