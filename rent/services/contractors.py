"""Contractor management services (US-05) - Jordon Stewart."""

import secrets
import re

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from rent.models import (
    Contractor,
    Shop,
    ShopAssignment,
    User,
    Role,
    PayType,
    RentPeriod,
)


# US-05 AC-1 and AC-2: Add and validate a contractor.
@transaction.atomic
def add_contractor(
    *,
    full_name,
    staff_id,
    shop,
    phone="",
    photo=None,
    pay_type=PayType.WEEKLY_RENT,
    password=None,
    joined_on=None
):
    full_name = (full_name or "").strip()
    staff_id = str(staff_id or "").strip()

    # Check that all required fields were entered.
    if not full_name:
        raise ValidationError("Full name is required.")

    if not staff_id:
        raise ValidationError("Staff ID is required.")

    if not isinstance(shop, Shop) or not shop.pk:
        raise ValidationError("A shop must be selected.")

    # Staff ID must contain exactly four digits.
    if not re.fullmatch(r"[0-9]{4}", staff_id):
        raise ValidationError("Staff ID must be exactly 4 digits.")

    # Prevent duplicate staff IDs.
    if Contractor.objects.filter(staff_id=staff_id).exists():
        raise ValidationError("Staff ID is already in use.")

    if pay_type not in PayType.values:
        raise ValidationError("Invalid payment type.")

    if joined_on is None:
        joined_on = timezone.localdate()

    if joined_on > timezone.localdate():
        raise ValidationError("Joining date cannot be in the future.")

    # Generate a username using the contractor's staff ID.
    username = "c" + staff_id

    if User.objects.filter(username=username).exists():
        raise ValidationError("This username is already in use.")

    # Generate a temporary password if one was not provided.
    if not password:
        password = secrets.token_urlsafe(12)

    if len(password) < 8:
        raise ValidationError("Password must have at least 8 characters.")

    names = full_name.split(maxsplit=1)

    # Create the login account with a hashed password.
    user = User.objects.create_user(
        username=username,
        password=password,
        first_name=names[0],
        last_name=names[1] if len(names) > 1 else "",
        role=Role.CONTRACTOR
    )

    # Create the contractor's profile.
    contractor = Contractor(
        user=user,
        full_name=full_name,
        staff_id=staff_id,
        shop=shop,
        phone=phone,
        pay_type=pay_type,
        joined_on=joined_on
    )

    if photo:
        contractor.photo = photo

    contractor.full_clean()
    contractor.save()

    # Store the contractor's first shop and payment type.
    ShopAssignment.objects.create(
        contractor=contractor,
        shop=shop,
        pay_type=pay_type,
        effective_from=RentPeriod.monday_of(joined_on)
    )

    # Allows the Owner's view to display the initial login password once.
    contractor.initial_password = password

    return contractor


# Update a contractor's personal details.
@transaction.atomic
def update_contractor(*, contractor, full_name, phone="", photo=None):
    full_name = (full_name or "").strip()

    if not full_name:
        raise ValidationError("Full name is required.")

    contractor.full_name = full_name
    contractor.phone = phone

    if photo:
        contractor.photo = photo

    contractor.full_clean()
    contractor.save()

    # Keep the login account's name up to date.
    names = full_name.split(maxsplit=1)

    contractor.user.first_name = names[0]
    contractor.user.last_name = names[1] if len(names) > 1 else ""
    contractor.user.save(update_fields=["first_name", "last_name"])

    return contractor


# Find the assignment that applies to a particular rent period.
def assignment_for(contractor, period):
    return ShopAssignment.objects.filter(
        contractor=contractor,
        effective_from__lte=period.start_date
    ).order_by("-effective_from").first()


# Return the shop assigned during a particular rent period.
def shop_for(contractor, period):
    assignment = assignment_for(contractor, period)

    if assignment:
        return assignment.shop

    return contractor.shop


# Return the payment type used during a particular rent period.
def pay_type_for(contractor, period):
    assignment = assignment_for(contractor, period)

    if assignment:
        return assignment.pay_type

    return contractor.pay_type


# Preserve the original assignment if one does not exist.
def ensure_initial_assignment(contractor):
    if not contractor.assignments.exists():
        ShopAssignment.objects.create(
            contractor=contractor,
            shop=contractor.shop,
            pay_type=contractor.pay_type,
            effective_from=RentPeriod.monday_of(contractor.joined_on)
        )


# US-05 AC-3: Move from commission to weekly rent.
@transaction.atomic
def change_pay_type(*, contractor, effective_period=None):
    contractor = Contractor.objects.select_for_update().get(
        pk=contractor.pk
    )

    if not contractor.is_active:
        raise ValidationError("This contractor is inactive.")

    next_period = RentPeriod.current().next()

    if effective_period is None:
        effective_period = next_period

    # Changes cannot affect the current or previous rent periods.
    if effective_period.start_date < next_period.start_date:
        raise ValidationError(
            "Payment changes must start from the next rent period or later."
        )

    ensure_initial_assignment(contractor)

    if pay_type_for(contractor, effective_period) != PayType.COMMISSION:
        raise ValidationError("This contractor is not on commission.")

    # Keep previous commission records and create a new rent assignment.
    assignment, created = ShopAssignment.objects.update_or_create(
        contractor=contractor,
        effective_from=effective_period.start_date,
        defaults={
            "shop": shop_for(contractor, effective_period),
            "pay_type": PayType.WEEKLY_RENT
        }
    )

    # Keep any later scheduled assignments on weekly rent as well.
    contractor.assignments.filter(
        effective_from__gt=effective_period.start_date
    ).update(pay_type=PayType.WEEKLY_RENT)

    return assignment


# US-05 AC-4: Transfer a contractor to another shop.
@transaction.atomic
def transfer(*, contractor, new_shop):
    contractor = Contractor.objects.select_for_update().get(
        pk=contractor.pk
    )

    if not contractor.is_active:
        raise ValidationError("Inactive contractors cannot be transferred.")

    if not isinstance(new_shop, Shop) or not new_shop.pk:
        raise ValidationError("A valid shop must be selected.")

    next_period = RentPeriod.current().next()

    ensure_initial_assignment(contractor)

    if shop_for(contractor, next_period) == new_shop:
        raise ValidationError("The contractor is already assigned to this shop.")

    # A supervisor must be replaced before transferring to another shop.
    if contractor.is_shop_supervisor:
        raise ValidationError(
            "Assign a replacement Shop Supervisor before transferring."
        )

    # Schedule the transfer for the next Monday.
    assignment, created = ShopAssignment.objects.update_or_create(
        contractor=contractor,
        effective_from=next_period.start_date,
        defaults={
            "shop": new_shop,
            "pay_type": pay_type_for(contractor, next_period)
        }
    )

    # Preserve any later payment-type changes at the new shop.
    contractor.assignments.filter(
        effective_from__gt=next_period.start_date
    ).update(shop=new_shop)

    return assignment


# US-05 AC-5: Assign or replace a Shop Supervisor.
@transaction.atomic
def set_shop_supervisor(*, shop, contractor):
    shop = Shop.objects.select_for_update().get(pk=shop.pk)

    contractor = Contractor.objects.select_for_update().get(
        pk=contractor.pk
    )

    if not contractor.is_active:
        raise ValidationError("An inactive contractor cannot supervise a shop.")

    # The supervisor must work at the selected shop.
    if shop_for(contractor, RentPeriod.current()) != shop:
        raise ValidationError("The contractor must work at this shop.")

    # Prevent a contractor from supervising multiple shops.
    if Shop.objects.filter(
        supervisor=contractor
    ).exclude(pk=shop.pk).exists():
        raise ValidationError("This contractor already supervises another shop.")

    # Remove the previous supervisor's role.
    old_supervisor = shop.supervisor

    if old_supervisor and old_supervisor != contractor:
        old_supervisor.user.role = Role.CONTRACTOR
        old_supervisor.user.save(update_fields=["role"])

    # Assign the new supervisor.
    shop.supervisor = contractor
    shop.save(update_fields=["supervisor"])

    contractor.user.role = Role.SHOP_SUPERVISOR
    contractor.user.save(update_fields=["role"])

    return contractor


# US-05 AC-6: Deactivate a contractor without deleting records.
@transaction.atomic
def deactivate(*, contractor):
    contractor = Contractor.objects.select_for_update().get(
        pk=contractor.pk
    )

    if not contractor.is_active:
        raise ValidationError("This contractor is already inactive.")

    # Ensure the shop still has a supervisor after deactivation.
    if contractor.is_shop_supervisor:
        raise ValidationError(
            "Assign a replacement Shop Supervisor before deactivating."
        )

    # Record when the contractor left.
    contractor.is_active = False
    contractor.deactivated_on = timezone.localdate()

    contractor.save(
        update_fields=["is_active", "deactivated_on"]
    )

    # Disable the login without deleting the account.
    contractor.user.is_active = False
    contractor.user.save(update_fields=["is_active"])

    return contractor


# US-05 AC-5: Create the Company Supervisor account.
@transaction.atomic
def create_company_supervisor(*, full_name, username, password):
    full_name = (full_name or "").strip()
    username = (username or "").strip()

    # Validate the required account details.
    if not full_name or not username or not password:
        raise ValidationError("Name, username and password are required.")

    if len(password) < 8:
        raise ValidationError("Password must have at least 8 characters.")

    # Only one active Company Supervisor is allowed.
    if User.objects.filter(
        role=Role.COMPANY_SUPERVISOR,
        is_active=True
    ).exists():
        raise ValidationError("An active Company Supervisor already exists.")

    if User.objects.filter(username=username).exists():
        raise ValidationError("Username is already in use.")

    names = full_name.split(maxsplit=1)

    return User.objects.create_user(
        username=username,
        password=password,
        first_name=names[0],
        last_name=names[1] if len(names) > 1 else "",
        role=Role.COMPANY_SUPERVISOR
    )


# US-05 AC-5: Deactivate the Company Supervisor account.
@transaction.atomic
def deactivate_company_supervisor(*, user):
    if user.role != Role.COMPANY_SUPERVISOR:
        raise ValidationError("This user is not a Company Supervisor.")

    # Disable login but preserve existing records.
    user.is_active = False
    user.save(update_fields=["is_active"])

    return user