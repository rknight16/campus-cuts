"""HandoffService (US-03) - owner: Chiantina Lawrence

This file contains the business logic for recording and confirming rent handoffs.

There are two types of handoffs:
1. Shop Supervisor -> Company Supervisor
2. Company Supervisor -> Owner

AC-2: The expected shop handoff amount is calculated from payments made
during the selected rent period.

AC-4: The expected owner handoff amount is calculated from the amounts
the Company Supervisor confirmed receiving from the shops.

AC-5: The system identifies whether the expected amount, amount handed
and amount received differ. The Handoff model handles the mismatch check.
"""

from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import DecimalValidator
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from rent.models import (
    Handoff,
    HandoffStatus,
    HandoffStep,
    Payment,
    Role,
)


def _validate_amount(value, field_name):
    """Check that an amount is valid and greater than zero."""
    try:
        # Convert the entered value to Decimal to avoid using float
        # for monetary calculations.
        amount = Decimal(str(value))

        # Reject special values such as NaN and Infinity.
        if not amount.is_finite():
            raise ValidationError({
                field_name: "Enter a valid amount."
            })

        # Ensure the amount has no more than 12 digits in total
        # and no more than 2 decimal places.
        DecimalValidator(12, 2)(amount)

    except (TypeError, ValueError, ArithmeticError, ValidationError):
        # Display an error if the amount cannot be converted
        # or does not meet the required format.
        raise ValidationError({
            field_name: "Enter a valid amount with no more than two decimal places."
        })

    # Handoff amounts must be greater than zero.
    if amount <= Decimal("0"):
        raise ValidationError({
            field_name: "The amount is invalid."
        })

    return amount


def _validate_handed_date(handed_date):
    """Handoff dates cannot be in the future (US-03 AC-6)."""
    if not handed_date:
        raise ValidationError({"handed_date": "A handoff date is required."})

    # Compare the entered date with today's date.
    # Future handoff dates are not allowed.
    if handed_date > timezone.localdate():
        raise ValidationError({
            "handed_date": "The handoff date cannot be in the future."
        })


def _shop_expected_amount(shop, period):
    """
    Calculate the expected amount for a shop.

    This is the total of all payments recorded for contractors
    belonging to the selected shop within the rent period (AC-2).
    """
    result = Payment.objects.filter(
        # Only include payments made by contractors at this shop.
        contractor__shop=shop,

        # Only include payments whose payment dates fall within
        # the selected rent period.
        payment_date__range=(period.start_date, period.end_date),
    ).aggregate(total=Sum("amount"))

    # Return the calculated total.
    # If no payments exist, return 0.00 instead of None.
    return result["total"] or Decimal("0.00")

def _owner_expected_amount(period):
    """
    Calculate the expected amount for the Company Supervisor's
    handoff to the Owner (AC-4).

    Only include shop handoffs that the Company Supervisor has confirmed.
    The amount_received field is used because it represents the money
    actually received by the Company Supervisor.
    """
    result = Handoff.objects.filter(
        # Only include handoffs from Shop Supervisors to the Company Supervisor.
        step=HandoffStep.SHOP_TO_COMPANY,
        # Only include handoffs for the selected rent period.
        rent_period=period,
        # Only include handoffs that have been confirmed.
        status=HandoffStatus.CONFIRMED,
    ).aggregate(total=Sum("amount_received")) # Add the confirmed amounts received.

    # Return the total confirmed amount.
    # If no shop handoffs have been confirmed, return 0.00.
    return result["total"] or Decimal("0.00")

def record_shop_handoff(*, shop, period, amount, handed_date, handed_by):
    """
    Record cash handed from a Shop Supervisor to the Company Supervisor.

    Each shop can have only one handoff per rent period.
    """
    # Check that the person recording the handoff is a Shop Supervisor.
    if handed_by.role != Role.SHOP_SUPERVISOR:
        raise PermissionDenied(
            "Only a Shop Supervisor can record a shop handoff."
        )

    # Check that the Shop Supervisor is assigned to the selected shop.
    # This prevents a supervisor from recording a handoff for another shop.
    if shop.supervisor_id is None or shop.supervisor.user_id != handed_by.pk:
        raise PermissionDenied(
            "You can only record a handoff for your own shop."
        )

    # Validate the amount and date before saving the handoff.
    amount = _validate_amount(amount, "amount")
    _validate_handed_date(handed_date)

    # Calculate how much money is expected based on the shop's payments.
    expected = _shop_expected_amount(shop, period)

    try:
        # Start a database transaction so the handoff is saved safely.
        with transaction.atomic():
            # Create and save the new shop handoff.
            handoff = Handoff.objects.create(
                step=HandoffStep.SHOP_TO_COMPANY,
                shop=shop,
                rent_period=period,
                expected_amount=expected,
                amount_handed=amount,
                handed_date=handed_date,
                handed_by=handed_by,
                status=HandoffStatus.AWAITING,
            )
    except IntegrityError:
        # The database prevents more than one shop handoff
        # for the same shop and rent period.
        raise ValidationError(
            "A handoff has already been recorded for this shop and rent period."
        )

    return handoff


def record_owner_handoff(*, period, amount, handed_date, handed_by):
    """
    Record cash handed from the Company Supervisor to the Owner.
    """
    # Only the Company Supervisor is allowed to record this handoff.
    if handed_by.role != Role.COMPANY_SUPERVISOR:
        raise PermissionDenied(
            "Only the Company Supervisor can record the owner handoff."
        )

    # Check that the amount and date are valid.
    amount = _validate_amount(amount, "amount")
    _validate_handed_date(handed_date)

    # Calculate the expected amount using the shop handoffs
    # that the Company Supervisor has already confirmed.
    expected = _owner_expected_amount(period)

    try:
        with transaction.atomic():
            # Create and save the Company Supervisor -> Owner handoff.
            handoff = Handoff.objects.create(
                step=HandoffStep.COMPANY_TO_OWNER,
                # This handoff covers all shops, so no individual shop is assigned.
                shop=None,
                rent_period=period,
                expected_amount=expected,
                amount_handed=amount,
                handed_date=handed_date,
                handed_by=handed_by,
                status=HandoffStatus.AWAITING,
            )
    except IntegrityError:
        raise ValidationError(
            "An owner handoff has already been recorded for this rent period."
        )

    return handoff


def confirm_handoff(*, handoff, amount_received, confirmed_by):
    """
    Confirm the amount actually received.

    The Company Supervisor confirms shop handoffs.
    The Owner confirms Company Supervisor -> Owner handoffs.
    """
    if handoff.pk is None:
        raise ValidationError("This handoff has not been saved.")

    amount_received = _validate_amount(
        amount_received, "amount_received"
    )

    with transaction.atomic():
        # Lock the record so two users cannot confirm it at the same time.
        handoff = Handoff.objects.select_for_update().get(pk=handoff.pk)

        if handoff.status == HandoffStatus.CONFIRMED:
            raise ValidationError("This handoff has already been confirmed.")

        # Check which type of handoff is being confirmed.
        if handoff.step == HandoffStep.SHOP_TO_COMPANY:
            # Only the Company Supervisor can confirm shop handoffs.
            if confirmed_by.role != Role.COMPANY_SUPERVISOR:
                raise PermissionDenied(
                    "Only the Company Supervisor can confirm shop handoffs."
                )

        elif handoff.step == HandoffStep.COMPANY_TO_OWNER:
            # Only the Owner can confirm the handoff from the Company Supervisor.
            if confirmed_by.role != Role.OWNER:
                raise PermissionDenied(
                    "Only the Owner can confirm the owner handoff."
                )

        else:
            # Reject the handoff if it does not have a recognised step.
            raise ValidationError("This handoff has an invalid step.")

         # Save the actual amount received.
        handoff.amount_received = amount_received
        # Record the user who confirmed the handoff.
        handoff.confirmed_by = confirmed_by
        # Record the exact date and time the confirmation took place.
        handoff.confirmed_at = timezone.now()
        # Change the handoff status from Awaiting confirmation to Confirmed.
        handoff.status = HandoffStatus.CONFIRMED

        # Save only the fields that were updated.
        handoff.save(update_fields=[
            "amount_received",
            "confirmed_by",
            "confirmed_at",
            "status",
        ])

    return handoff

