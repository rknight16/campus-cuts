"""US-07 Payment receipts on WhatsApp - owner: Jordon Mingoes"""
from django.shortcuts import render

from rent.access import role_required
from rent.models import Role


@role_required(Role.SHOP_SUPERVISOR)
def receipts(request):
    # TODO: build this page. Call rent.services.receipts for the rules.
    return render(request, "rent/placeholder.html", {"title": "Receipts", "owner": "Jordon Mingoes"})
