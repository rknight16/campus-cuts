"""RentSettingsService (US-02) - owner: Jordon Mingoes

set_rent: validate amount and due day (AC-2), save a new RentSetting that
starts from the NEXT rent period (AC-4), so earlier periods keep old rent.
"""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied, ValidationError

from rent.models import RentPeriod, RentSetting, Role, Shop, Weekday

from rent.services.contractors import shop_for

CENTS = Decimal("0.01")
# RentSetting.weekly_rent holds at most 99,999,999.99
MAX_RENT = Decimal("100000000")
AMOUNT_INVALID = "The amount is invalid."
DUE_DAY_MISSING = "Select a due day."


def _clean_amount(value):
    """Return the rent as a Decimal in cents, or raise ValidationError (AC-2)."""
    try:
        amount = Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, ValueError):
        raise ValidationError(AMOUNT_INVALID)
    if not amount.is_finite() or amount >= MAX_RENT:
        raise ValidationError(AMOUNT_INVALID)
    amount = amount.quantize(CENTS, rounding=ROUND_HALF_UP)
    if amount <= 0:
        raise ValidationError(AMOUNT_INVALID)
    return amount


def _clean_due_day(value):
    """Return the due day as 0 (Monday) to 6 (Sunday), or raise ValidationError (AC-2)."""
    try:
        day = int(value)
    except (TypeError, ValueError):
        raise ValidationError(DUE_DAY_MISSING)
    if day not in Weekday.values:
        raise ValidationError(DUE_DAY_MISSING)
    return day


def _shops_for(user):
    """Shops whose rent changes this user is told about (AC-5)."""
    if user.role == Role.COMPANY_SUPERVISOR:
        return Shop.objects.all()
    # contractors and Shop Supervisors
    profile = getattr(user, "contractor_profile", None)
    if user.role != Role.OWNER and profile is not None:
        return Shop.objects.filter(pk=shop_for(profile, RentPeriod.current()).pk)
    return Shop.objects.none()


def set_rent(*, shop, weekly_rent, due_day, set_by):
    """Save the shop's rent and due day from the NEXT rent period (AC-1, AC-2, AC-4)."""
    if set_by.role != Role.OWNER:
        raise PermissionDenied("Only the Owner can set the rent.")
    amount = _clean_amount(weekly_rent)
    day = _clean_due_day(due_day)
    start = RentPeriod.current().next()
    setting, _ = RentSetting.objects.update_or_create(
        shop=shop,
        effective_from=start,
        defaults={"weekly_rent": amount, "due_day": day, "created_by": set_by},
    )
    return setting


def pending_rent_notices(user):
    """Rent changes this user should be told about at login (AC-5).

    A change is a setting that starts this week or later AND replaces an
    earlier setting for the same shop. Returns a list of dicts for the template.
    """
    current = RentPeriod.current()
    settings = (
        RentSetting.objects.filter(
            shop__in=_shops_for(user),
            effective_from__start_date__gte=current.start_date,
        )
        .select_related("shop", "effective_from")
        .order_by("shop__name", "effective_from__start_date")
    )
    notices = []
    for s in settings:
        start = s.effective_from.start_date
        is_change = RentSetting.objects.filter(
            shop=s.shop, effective_from__start_date__lt=start
        ).exists()
        if not is_change:
            continue
        notices.append({
            "shop": s.shop,
            "weekly_rent": s.weekly_rent,
            "due_day": s.get_due_day_display(),
            "start_date": start,
            "message": (
                f"Rent at {s.shop} is changing to ${s.weekly_rent:,.2f}, due every "
                f"{s.get_due_day_display()}, starting {start.day} {start:%b %Y}."
            ),
        })
    return notices
