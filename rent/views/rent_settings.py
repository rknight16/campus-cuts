"""US-02 Set weekly rent and due day - owner: Jordon Mingoes"""
from django.core.exceptions import ValidationError
from django.shortcuts import render

from rent.access import role_required
from rent.models import RentPeriod, RentSetting, Role, Shop, Weekday
from rent.services import rent_settings as rent_service


def _shop_from_form(request):
    """The shop picked in the form, or None."""
    try:
        return Shop.objects.get(pk=int(request.POST.get("shop", "")))
    except (ValueError, Shop.DoesNotExist):
        return None


@role_required(Role.OWNER)
def rent_settings(request):
    saved, error = None, None

    if request.method == "POST":
        shop = _shop_from_form(request)
        if shop is None:
            error = "Select a shop."
        else:
            try:
                saved = rent_service.set_rent(
                    shop=shop,
                    weekly_rent=request.POST.get("weekly_rent"),
                    due_day=request.POST.get("due_day"),
                    set_by=request.user,
                )
            except ValidationError as exc:
                error = " ".join(exc.messages)

    # Table of what each shop pays now and what is coming next period
    period = RentPeriod.current()
    next_period = period.next()
    rows = []
    for shop in Shop.objects.all():
        now = RentSetting.for_shop(shop, period)
        upcoming = RentSetting.for_shop(shop, next_period)
        rows.append({"shop": shop, "now": now, "upcoming": upcoming if upcoming != now else None})

    return render(request, "rent/rent_settings.html", {
        "shops": Shop.objects.all(),
        "weekdays": Weekday.choices,
        "rows": rows,
        "period": period,
        "next_period": next_period,
        "saved": saved,
        "error": error,
        "posted": request.POST if error else {},  # keep what they typed if it failed
    })