"""Home pages: after login each role lands on its own page (SDS 2.3.1)."""
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import redirect, render

from rent.access import contractors_visible_to, role_required
from rent.models import Role, RentPeriod, Shop
from rent.services import rent_rules

# Who needs attention first on the supervisor's list
STATUS_ORDER = {
    rent_rules.UNPAID: 0,
    rent_rules.PARTLY_PAID: 1,
    rent_rules.AWAITING_EARNINGS: 2,
    rent_rules.PAID: 3,
}


@login_required
def home(request):
    """Send each user to the home page for their role."""
    return redirect({
        Role.OWNER: "owner_home",
        Role.COMPANY_SUPERVISOR: "company_home",
        Role.SHOP_SUPERVISOR: "supervisor_home",
        Role.CONTRACTOR: "my_account",
    }[request.user.role])


def _shops_page(request, heading):
    shops = Shop.objects.select_related("supervisor").annotate(
        active_contractors=Count("contractors", filter=Q(contractors__is_active=True)))
    return render(request, "rent/home_shops.html", {
        "heading": heading,
        "shops": shops,
        "period": RentPeriod.current(),
    })


@role_required(Role.OWNER)
def owner_home(request):
    return _shops_page(request, "Your shops")


@role_required(Role.COMPANY_SUPERVISOR)
def company_home(request):
    return _shops_page(request, "All shops")


def supervisor_rows(contractors, period, today=None):
    """One row per contractor: this week's summary plus any overdue balance.

    Sorted so anyone overdue comes first, then by this week's status
    (unpaid, partly paid, earnings not entered, paid), then by name.
    """
    rows = []
    for c in contractors:
        overdue = rent_rules.overdue_periods(c, today)
        rows.append({
            "contractor": c,
            "summary": rent_rules.summary(c, period),
            "overdue_total": sum((owing for _, owing in overdue), rent_rules.ZERO),
        })
    rows.sort(key=lambda r: (not r["overdue_total"], STATUS_ORDER.get(r["summary"]["status"], 9),
                             r["contractor"].full_name))
    return rows


@role_required(Role.SHOP_SUPERVISOR)
def supervisor_home(request):
    # Only this supervisor's shop (US-01 AC-5)
    period = RentPeriod.current()
    rows = supervisor_rows(contractors_visible_to(request.user).filter(is_active=True), period)
    return render(request, "rent/home_supervisor.html", {
        "shop": request.user.supervised_shop,
        "rows": rows,
        "period": period,
        "paid_count": sum(1 for r in rows if r["summary"]["status"] == rent_rules.PAID),
        "outstanding": sum((r["summary"]["balance"] or rent_rules.ZERO for r in rows), rent_rules.ZERO),
    })
