"""US-03 Record and confirm handoffs - owner: Chiantina Lawrence"""
from django.shortcuts import render

from rent.access import role_required
from rent.models import Role


@role_required(Role.SHOP_SUPERVISOR, Role.COMPANY_SUPERVISOR, Role.OWNER)
def handoffs(request):
    # TODO: build this page. Call rent.services.handoffs for the rules.
    return render(request, "rent/placeholder.html", {"title": "Rent handoffs", "owner": "Chiantina Lawrence"})
