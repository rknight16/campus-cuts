"""US-01 Record rent payments - owner: Raynardo Knight"""
from django.shortcuts import render

from rent.access import role_required
from rent.models import Role


@role_required(Role.SHOP_SUPERVISOR)
def record_payment(request):
    # TODO: build this page. Call rent.services.payments for the rules.
    return render(request, "rent/placeholder.html", {"title": "Record a payment", "owner": "Raynardo Knight"})
