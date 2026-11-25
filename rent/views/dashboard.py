"""US-04 Rent collection dashboard - owner: Dylandre Henry"""
from django.shortcuts import render

from rent.access import role_required
from rent.models import Role
from rent.services import dashboard as dashboard_service


@role_required(Role.OWNER, Role.COMPANY_SUPERVISOR)
def dashboard(request):
    data = dashboard_service.shop_summary()
    return render(request, "rent/dashboard.html", data)
