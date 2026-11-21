"""PaymentService (US-01) - owner: Raynardo Knight

record_payment: validate (AC-2, AC-3) and save; creates a Receipt (US-07).
correct_payment: needs a reason, keeps the original in PaymentCorrection (AC-7).
Never delete a Payment (SF-1); the model blocks it anyway.
"""


def record_payment(*, contractor, period, amount, payment_date, recorded_by):
    raise NotImplementedError


def correct_payment(*, payment, new_amount, new_payment_date, reason, corrected_by):
    raise NotImplementedError


def enter_commission_earnings(*, contractor, period, earnings, entered_by):
    raise NotImplementedError
