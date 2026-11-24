"""PaymentService (US-01) - owner: Raynardo Knight

record_payment: validate (AC-2, AC-3, AC-5) and save the payment (AC-1).
correct_payment: needs a reason, keeps the original in PaymentCorrection (AC-7).
enter_commission_earnings: earnings for a commission contractor (AC-6).
Never delete a Payment (SF-1); the model blocks it anyway.

Rule breaks raise django.core.exceptions.ValidationError with a message the
page can show as is. Acting on another shop raises PermissionDenied (403).
"""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from rent.access import ensure_same_shop
from rent.formatting import format_money
from rent.models import (CommissionEarning, Contractor, PayType, Payment,
                         PaymentCorrection, RentPeriod, Role)
from rent.services import rent_rules

REASON_MAX_LENGTH = PaymentCorrection._meta.get_field("reason").max_length


# ---------------------------------------------------------------------------
# Checks shared by the functions below
# ---------------------------------------------------------------------------

def _ensure_shop_supervisor_of(user, contractor):
    """AC-5: only the Shop Supervisor of the contractor's own shop may do this."""
    if user is None or user.role != Role.SHOP_SUPERVISOR:
        raise PermissionDenied("Only a Shop Supervisor can record payments.")
    ensure_same_shop(user, contractor.shop)


def _to_money(value, field="amount"):
    """Turn form input into a Decimal with at most 2 decimal places (never float)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValidationError(f"Enter the {field}.")
    if isinstance(value, float):
        value = str(value)  # avoid float rounding errors
    try:
        amount = Decimal(str(value).strip().replace(",", "").lstrip("$"))
    except (InvalidOperation, ValueError):
        raise ValidationError(f"The {field} must be a number, for example 15000.")
    if not amount.is_finite():
        raise ValidationError(f"The {field} must be a number, for example 15000.")
    if amount != amount.quantize(rent_rules.CENTS):
        raise ValidationError(f"The {field} can have at most 2 decimal places.")
    return amount.quantize(rent_rules.CENTS)


def _to_date(value):
    if value is None or value == "":
        raise ValidationError("Enter the payment date.")
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        raise ValidationError("Enter a real payment date.")


def _check_period(period, today):
    """AC-3: the rent period is required and cannot be after the current period."""
    if period is None:
        raise ValidationError("Choose the rent period.")
    if period.start_date > RentPeriod.monday_of(today):
        raise ValidationError("You cannot record rent for a future rent period.")


def _check_payment_date(payment_date, today):
    """AC-3: the payment date cannot be in the future."""
    if payment_date > today:
        raise ValidationError("The payment date cannot be in the future.")


def _check_amount_fits(amount, owed, already_paid):
    """AC-2: amount above 0 and no more than what is still owed."""
    if amount <= 0:
        raise ValidationError("The amount must be more than $0.")
    most = max(owed - already_paid, rent_rules.ZERO)
    if most == 0:
        raise ValidationError("This rent period is already paid in full. Nothing more can be recorded.")
    if amount > most:
        raise ValidationError(
            f"That is more than the balance. The most you can record is {format_money(most)}."
        )


def _owed_or_error(contractor, period):
    owed = rent_rules.amount_owed(contractor, period)
    if owed is None:
        if contractor.pay_type == PayType.COMMISSION:
            raise ValidationError(
                "Enter this contractor's commission earnings for the rent period first."
            )
        raise ValidationError("No weekly rent is set for this shop for that rent period.")
    return owed


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------

def record_payment(*, contractor, period, amount, payment_date, recorded_by):
    """Record a cash payment (full or part) and return the Payment (AC-1).

    Deactivated contractors can still pay off a balance (US-05 AC-6).
    """
    if contractor is None:
        raise ValidationError("Choose the contractor.")
    _ensure_shop_supervisor_of(recorded_by, contractor)
    today = timezone.localdate()
    _check_period(period, today)
    amount = _to_money(amount)
    payment_date = _to_date(payment_date)
    _check_payment_date(payment_date, today)
    if amount <= 0:
        raise ValidationError("The amount must be more than $0.")

    with transaction.atomic():
        # Lock the contractor row so two supervisors saving at once cannot
        # together go over the balance.
        contractor = Contractor.objects.select_for_update().get(pk=contractor.pk)
        owed = _owed_or_error(contractor, period)
        _check_amount_fits(amount, owed, rent_rules.amount_paid(contractor, period))
        payment = Payment.objects.create(
            contractor=contractor, rent_period=period, amount=amount,
            payment_date=payment_date, recorded_by=recorded_by,
        )
        # TODO(US-07): create_receipt(payment)
    return payment


def correct_payment(*, payment, new_amount, new_payment_date, reason, corrected_by):
    """Change a payment's amount and/or date, keeping the original (AC-7, SF-1).

    A PaymentCorrection row stores the old and new values, the reason, who and
    when. The Payment then holds the corrected values. Nothing is deleted.
    """
    _ensure_shop_supervisor_of(corrected_by, payment.contractor)
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("Enter a reason for the correction.")
    if len(reason) > REASON_MAX_LENGTH:
        raise ValidationError(f"Keep the reason under {REASON_MAX_LENGTH} characters.")
    today = timezone.localdate()
    new_amount = _to_money(new_amount)
    new_payment_date = _to_date(new_payment_date)
    _check_payment_date(new_payment_date, today)
    if new_amount <= 0:
        raise ValidationError("The amount must be more than $0.")

    with transaction.atomic():
        Contractor.objects.select_for_update().get(pk=payment.contractor_id)
        payment = Payment.objects.select_for_update().get(pk=payment.pk)
        if new_amount == payment.amount and new_payment_date == payment.payment_date:
            raise ValidationError("Nothing has changed. Change the amount or the date.")
        contractor, period = payment.contractor, payment.rent_period
        owed = _owed_or_error(contractor, period)
        others = rent_rules.amount_paid(contractor, period, exclude_payment=payment)
        _check_amount_fits(new_amount, owed, others)

        PaymentCorrection.objects.create(
            payment=payment,
            old_amount=payment.amount, new_amount=new_amount,
            old_payment_date=payment.payment_date, new_payment_date=new_payment_date,
            reason=reason, corrected_by=corrected_by,
        )
        payment.amount = new_amount
        payment.payment_date = new_payment_date
        payment.save(update_fields=["amount", "payment_date"])
        # TODO(US-07): create_receipt(payment, corrects=<previous receipt>) for a corrected receipt (US-07 AC-4)
    return payment


def enter_commission_earnings(*, contractor, period, earnings, entered_by):
    """Create or update the earnings for a commission contractor (AC-6).

    Amount owed then becomes 40% of earnings ($30,000 earnings -> $12,000 owed).
    """
    _ensure_shop_supervisor_of(entered_by, contractor)
    if contractor.pay_type != PayType.COMMISSION:
        raise ValidationError(f"{contractor.full_name} pays weekly rent, not commission.")
    _check_period(period, timezone.localdate())
    earnings = _to_money(earnings, field="earnings")
    if earnings < 0:
        raise ValidationError("Earnings cannot be below $0.")

    with transaction.atomic():
        contractor = Contractor.objects.select_for_update().get(pk=contractor.pk)
        paid = rent_rules.amount_paid(contractor, period)
        if rent_rules.commission_owed(earnings) < paid:
            raise ValidationError(
                f"{format_money(paid)} is already recorded for this period, so the 40% share "
                f"cannot be less than that. Correct the payment first if it is wrong."
            )
        earning, _ = CommissionEarning.objects.update_or_create(
            contractor=contractor, rent_period=period,
            defaults={"earnings": earnings, "entered_by": entered_by},
        )
    return earning
