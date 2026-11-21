"""RentRules (US-01 AC-6, US-04, US-06) - owner: Raynardo Knight

Works out what a contractor owes for a rent period and their status.
Used by payments, dashboard, account page and receipts, so build this first.
"""
from decimal import Decimal

COMMISSION_SHARE = Decimal("0.40")  # shop gets 40% of earnings (SRS 1.1)


def amount_owed(contractor, period):
    """Shop's weekly rent for the period (RentSetting.for_shop), or 40% of
    CommissionEarning.earnings if the contractor is on commission."""
    raise NotImplementedError


def amount_paid(contractor, period):
    """Sum of Payment.amount for this contractor and period."""
    raise NotImplementedError


def balance(contractor, period):
    raise NotImplementedError


def status(contractor, period):
    """'Paid', 'Partly paid' or 'Unpaid' (SRS section 4)."""
    raise NotImplementedError


def overdue_periods(contractor, today=None):
    """List of (period, balance) still owed after the end of the due day."""
    raise NotImplementedError
