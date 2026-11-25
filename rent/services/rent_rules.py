"""RentRules (US-01 AC-6, US-04, US-06) - owner: Raynardo Knight

Works out what a contractor owes for a rent period and their status.
Used by payments, dashboard, account page and receipts, so build this first.

All money is Decimal (never float).

Commission contractors with no earnings entered yet
---------------------------------------------------
The SRS says the amount owed is shown once the Shop Supervisor enters the
earnings (US-01 AC-6). Until then amount_owed() and balance() return None and
status() returns AWAITING_EARNINGS. Callers must handle None, for example:

    owed = rent_rules.amount_owed(contractor, period)
    if owed is None:
        ...  # show "Earnings not entered yet"
"""
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Sum
from django.utils import timezone

from rent.models import CommissionEarning, PayType, Payment, RentPeriod, RentSetting
from rent.services.contractors import shop_for, pay_type_for

COMMISSION_SHARE = Decimal("0.40")  # shop gets 40% of earnings (SRS 1.1)
CENTS = Decimal("0.01")
ZERO = Decimal("0.00")

# Status values (SRS section 4). AWAITING_EARNINGS is only used for a
# commission contractor whose earnings for the period are not entered yet.
PAID = "Paid"
PARTLY_PAID = "Partly paid"
UNPAID = "Unpaid"
AWAITING_EARNINGS = "Earnings not entered"


def commission_earnings(contractor, period):
    """The CommissionEarning row for this contractor and period, or None."""
    return CommissionEarning.objects.filter(contractor=contractor, rent_period=period).first()


def commission_owed(earnings):
    """The shop's 40% share of `earnings`, rounded to cents ($30,000 -> $12,000.00)."""
    return (COMMISSION_SHARE * earnings).quantize(CENTS, rounding=ROUND_HALF_UP)


def amount_owed(contractor, period):
    """Calculates how much a contractor owes for a rent period."""

    # AC-6: Stop charging rent for weeks after deactivation.
    if contractor.deactivated_on:
        if period.start_date > contractor.deactivated_on:
            return ZERO

    # AC-3: Use the payment type that applied during this week.
    if pay_type_for(contractor, period) == PayType.COMMISSION:
        if period.pk is None:
            return None

        earning = commission_earnings(contractor, period)

        if earning is None:
            return None

        return commission_owed(earning.earnings)

    # AC-4: Use the shop assigned during this rent period.
    setting = RentSetting.for_shop(shop_for(contractor, period), period)

    if setting is None:
        return None

    return setting.weekly_rent


def amount_paid(contractor, period, exclude_payment=None):
    """Sum of Payment.amount for this contractor and period.

    `exclude_payment` leaves one payment out (used when correcting it, so the
    new amount is checked against the *other* payments for the period).
    """
    qs = Payment.objects.filter(contractor=contractor, rent_period=period)
    if exclude_payment is not None:
        qs = qs.exclude(pk=exclude_payment.pk)
    total = qs.aggregate(total=Sum("amount"))["total"]
    return total if total is not None else ZERO


def balance(contractor, period):
    """Owed minus paid, never below 0. None if the amount owed is not known yet."""
    owed = amount_owed(contractor, period)
    if owed is None:
        return None
    return max(owed - amount_paid(contractor, period), ZERO)


def status(contractor, period):
    """'Paid', 'Partly paid' or 'Unpaid' (SRS section 4).

    'Earnings not entered' for a commission contractor with no earnings yet.
    """
    owed = amount_owed(contractor, period)
    if owed is None:
        return AWAITING_EARNINGS
    paid = amount_paid(contractor, period)
    if paid >= owed:
        return PAID
    if paid > 0:
        return PARTLY_PAID
    return UNPAID


def summary(contractor, period):
    """Owed, paid, balance and status in one dict, for pages and receipts."""
    owed = amount_owed(contractor, period)
    paid = amount_paid(contractor, period)
    return {
        "owed": owed,
        "paid": paid,
        "balance": None if owed is None else max(owed - paid, ZERO),
        "status": status(contractor, period),
    }


def due_date(contractor, period):
    """The day rent is due in `period`: the shop's due day that week (US-02 AC-3). None if no rent is set."""
    setting = RentSetting.for_shop(shop_for(contractor, period), period)
    if setting is None:
        return None
    return period.due_date_for(setting.due_day)


def weeks_since_joining(contractor, today=None):
    """Every rent period from the week the contractor joined up to the current one, oldest first.

    A week nobody opened the system in has no RentPeriod row yet. It is still included, as an
    unsaved RentPeriod, so an unpaid week can never be skipped. Nothing is saved here.
    """
    if today is None:
        today = timezone.localdate()
    first = RentPeriod.monday_of(contractor.joined_on)
    last = RentPeriod.monday_of(today)
    saved = {p.start_date: p for p in RentPeriod.objects.filter(start_date__gte=first, start_date__lte=last)}
    start = first
    while start <= last:
        yield saved.get(start) or RentPeriod(start_date=start, end_date=start + timedelta(days=6))
        start += timedelta(days=7)


def _balance_for_week(contractor, period):
    """Calculates the balance for saved and unsaved rent periods."""

    if period.pk is not None:
        return balance(contractor, period)

    # Uses the updated rent calculation for assignment history
    # and deactivated contractors (US-05).
    return amount_owed(contractor, period)


def overdue_periods(contractor, today=None):
    """List of (period, balance) still owed after the end of the due day, oldest first.

    Only weeks from the one the contractor joined (Contractor.joined_on) count, so a new
    contractor is never overdue for weeks before they started. A period is overdue when its
    balance is above 0 and `today` is after period.due_date_for(setting.due_day). Periods where
    the amount owed is not known yet (commission with no earnings) are not counted.
    """
    if today is None:
        today = timezone.localdate()
    overdue = []
    for period in weeks_since_joining(contractor, today):
        due = due_date(contractor, period)
        if due is None:
            continue  # no rent was set for this shop yet
        if today <= due:
            continue  # not due yet (the due day itself is still on time)
        owing = _balance_for_week(contractor, period)
        if owing:  # skips None and 0
            overdue.append((period, owing))
    return overdue


def account_overview(contractor, today=None):
    """Everything the contractor's own account page shows (US-06 AC-1, AC-2), in one call.

    This week: owed, paid, balance, status (from summary()), the due date and whether it has
    passed. Overdue: each overdue week with its balance and due date, and the total.
    """
    if today is None:
        today = timezone.localdate()
    period = RentPeriod.for_date(today)
    week = summary(contractor, period)
    due = due_date(contractor, period)
    overdue = [
        {"period": p, "balance": owing, "due_date": due_date(contractor, p)}
        for p, owing in overdue_periods(contractor, today)
    ]
    return {
        "period": period,
        **week,
        "due_date": due,
        "due_passed": due is not None and today > due,
        "overdue": overdue,
        "overdue_total": sum((row["balance"] for row in overdue), ZERO),
    }
