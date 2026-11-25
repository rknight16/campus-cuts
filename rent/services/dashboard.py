"""DashboardService (US-04) - owner: Dylandre Henry

Read-only summary for the Owner and Company Supervisor. Uses rent_rules for
owed/paid/balance/overdue per shop and lists each shop's handoff status.
Every shop is listed, even with $0 paid (AC-4).
"""
from django.utils import timezone

from rent.models import Contractor, Handoff, HandoffStep, RentPeriod, Shop
from rent.services import rent_rules
from rent.services.contractors import shop_for

ZERO = rent_rules.ZERO


def shop_summary(today=None):
    """One row per shop for the current rent period, plus totals for all shops."""
    if today is None:
        today = timezone.localdate()
    period = RentPeriod.for_date(today)
    handoffs = {
        h.shop_id: h
        for h in Handoff.objects.filter(step=HandoffStep.SHOP_TO_COMPANY, rent_period=period)
    }

    # Every shop gets a row first, so a shop with nobody paid is still listed (AC-4)
    rows = {
        shop.pk: {
            "shop": shop, "owed": ZERO, "paid": ZERO, "balance": ZERO, "overdue": ZERO,
            "awaiting_earnings": 0, "handoff": handoffs.get(shop.pk),
        }
        for shop in Shop.objects.select_related("supervisor")
    }

    # Deactivated contractors stay in: rent_rules charges them nothing after deactivated_on,
    # but any balance they still owe stays overdue (US-05 AC-6).
    for contractor in Contractor.objects.all():
        # US-05 AC-4: the shop the contractor is assigned to in this period
        row = rows[shop_for(contractor, period).pk]
        week = rent_rules.summary(contractor, period)
        row["paid"] += week["paid"]
        if week["owed"] is None:
            row["awaiting_earnings"] += 1   # commission, earnings not entered yet
        else:
            row["owed"] += week["owed"]
            row["balance"] += week["balance"]
        row["overdue"] += sum(
            (owing for _, owing in rent_rules.overdue_periods(contractor, today)), ZERO)

    shop_rows = list(rows.values())
    totals = {key: sum((r[key] for r in shop_rows), ZERO) for key in ("owed", "paid", "balance", "overdue")}
    return {"period": period, "shops": shop_rows, "totals": totals}