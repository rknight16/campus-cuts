"""US-04 Rent collection dashboard - owner: Dylandre Henry"""
from django.shortcuts import render

from rent.access import role_required
from rent.models import Role


@role_required(Role.OWNER, Role.COMPANY_SUPERVISOR)
def dashboard(request):
    # TODO: build this page. Call rent.services.dashboard for the rules.
    return render(request, "rent/placeholder.html", {"title": "Rent collection dashboard", "owner": "Dylandre Henry"})
