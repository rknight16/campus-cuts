"""Home pages: after login each role lands on its own page (SDS 2.3.1)."""
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import redirect, render

from rent.access import contractors_visible_to, role_required
from rent.models import Contractor, Handoff, HandoffStatus, HandoffStep, PayType, Role, RentPeriod, Shop
from rent.services import rent_settings
from rent.services import rent_rules
from rent.services.contractors import pay_type_for, shop_for

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
    # US-02 AC-5: tell the user about rent changes once per login
    if not request.session.get("rent_notices_shown"):
        for notice in rent_settings.pending_rent_notices(request.user):
            messages.info(request, notice["message"])
        request.session["rent_notices_shown"] = True
    return redirect({
        Role.OWNER: "owner_home",
        Role.COMPANY_SUPERVISOR: "company_home",
        Role.SHOP_SUPERVISOR: "supervisor_home",
        Role.CONTRACTOR: "my_account",
    }[request.user.role])


def waiting_handoffs(user):
    """Handoffs this user still has to confirm: shop handoffs for the Company Supervisor,
    the Company Supervisor's handoff for the Owner."""
    step = {Role.COMPANY_SUPERVISOR: HandoffStep.SHOP_TO_COMPANY, Role.OWNER: HandoffStep.COMPANY_TO_OWNER}.get(user.role)
    if step is None:
        return Handoff.objects.none()
    return Handoff.objects.filter(step=step, status=HandoffStatus.AWAITING)


def shop_cards(shops, period, last_period, user, today=None):
    """Each shop's week in money, plus last week's handoff, so the home page answers "is the money in?".

    Collected and still-to-collect are for this week; overdue is anything older still owed.
    Last week's handoff is shown because cash is usually handed over after the week ends.
    """
    handoffs = {h.shop_id: h for h in Handoff.objects.filter(step=HandoffStep.SHOP_TO_COMPANY, rent_period=last_period)}
    cards = []
    for shop in shops:
        collected = outstanding = overdue = rent_rules.ZERO
        for contractor in Contractor.objects.filter(is_active=True):

            # AC-4: Only include contractors assigned to this shop for the period.
            if shop_for(contractor, period) != shop:
                continue
            week = rent_rules.summary(contractor, period)
            collected += week["paid"]
            outstanding += week["balance"] or rent_rules.ZERO
            overdue += sum((owing for _, owing in rent_rules.overdue_periods(contractor, today)), rent_rules.ZERO)
        handoff = handoffs.get(shop.pk)
        cards.append({
            "shop": shop,
            "collected": collected,
            "outstanding": outstanding,
            "overdue": overdue,
            "handoff": handoff,
            "needs_action": (handoff is not None and handoff.status == HandoffStatus.AWAITING
                             and user.role == Role.COMPANY_SUPERVISOR),
        })
    return cards


def _shops_page(request, heading):
    period = RentPeriod.current()
    shops = Shop.objects.select_related("supervisor")
    contractors = Contractor.objects.filter(is_active=True)

    # Count contractors using their assigned shop for the current week.
    for shop in shops:
        shop.active_contractors = sum(
            1 for contractor in contractors
            if shop_for(contractor, period) == shop
        )
    last_period = RentPeriod.for_date(period.start_date - timedelta(days=7))
    cards = shop_cards(shops, period, last_period, request.user)
    return render(request, "rent/home_shops.html", {
        "heading": heading,
        "cards": cards,
        "period": period,
        "last_period": last_period,
        "waiting_count": waiting_handoffs(request.user).count(),
        "collected": sum((c["collected"] for c in cards), rent_rules.ZERO),
        "outstanding": sum((c["outstanding"] for c in cards), rent_rules.ZERO),
        "overdue": sum((c["overdue"] for c in cards), rent_rules.ZERO),
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
            # The pay type for this week, so a scheduled change (US-05 AC-3) shows once it applies
            "pay_type": PayType(pay_type_for(c, period)).label,
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
