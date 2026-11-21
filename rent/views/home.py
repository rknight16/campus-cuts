"""Home pages: after login each role lands on its own page (SDS 2.3.1)."""
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from rent.access import contractors_visible_to, role_required
from rent.models import Role, RentPeriod, Shop


@login_required
def home(request):
    """Send each user to the home page for their role."""
    return redirect({
        Role.OWNER: "owner_home",
        Role.COMPANY_SUPERVISOR: "company_home",
        Role.SHOP_SUPERVISOR: "supervisor_home",
        Role.CONTRACTOR: "my_account",
    }[request.user.role])


@role_required(Role.OWNER)
def owner_home(request):
    return render(request, "rent/home_owner.html", {
        "shops": Shop.objects.select_related("supervisor"),
        "period": RentPeriod.current(),
    })


@role_required(Role.COMPANY_SUPERVISOR)
def company_home(request):
    return render(request, "rent/home_company.html", {
        "shops": Shop.objects.select_related("supervisor"),
        "period": RentPeriod.current(),
    })


@role_required(Role.SHOP_SUPERVISOR)
def supervisor_home(request):
    # Only this supervisor's shop (US-01 AC-5)
    return render(request, "rent/home_supervisor.html", {
        "shop": request.user.supervised_shop,
        "contractors": contractors_visible_to(request.user).filter(is_active=True),
        "period": RentPeriod.current(),
    })
