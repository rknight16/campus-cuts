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
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Sum
from django.utils import timezone

from rent.models import CommissionEarning, PayType, Payment, RentPeriod, RentSetting

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
    """What the contractor owes for `period`.

    Weekly rent: the shop's weekly rent in force for that period
    (RentSetting.for_shop), so a later rent change never alters old periods.
    Commission: 40% of the earnings entered for that period, rounded to cents.

    Returns None when it cannot be worked out yet: a commission contractor with
    no earnings entered, or a shop with no rent setting for that period.
    """
    if contractor.pay_type == PayType.COMMISSION:
        earning = commission_earnings(contractor, period)
        if earning is None:
            return None
        return commission_owed(earning.earnings)

    setting = RentSetting.for_shop(contractor.shop, period)
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


def overdue_periods(contractor, today=None):
    """List of (period, balance) still owed after the end of the due day.

    A period is overdue when its balance is above 0 and `today` is after
    period.due_date_for(setting.due_day). Periods where the amount owed is not
    known yet (commission with no earnings) are not counted. Oldest first.
    """
    if today is None:
        today = timezone.localdate()
    overdue = []
    periods = RentPeriod.objects.filter(start_date__lte=today).order_by("start_date")
    for period in periods:
        setting = RentSetting.for_shop(contractor.shop, period)
        if setting is None:
            continue  # no rent was set for this shop yet
        if today <= period.due_date_for(setting.due_day):
            continue  # not due yet (the due day itself is still on time)
        owing = balance(contractor, period)
        if owing:  # skips None and 0
            overdue.append((period, owing))
    return overdue
