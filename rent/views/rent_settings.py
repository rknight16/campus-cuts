"""US-02 Set weekly rent and due day - owner: Jordon Mingoes"""
from django.shortcuts import render

from rent.access import role_required
from rent.models import Role


@role_required(Role.OWNER)
def rent_settings(request):
    # TODO: build this page. Call rent.services.rent_settings for the rules.
    return render(request, "rent/placeholder.html", {"title": "Weekly rent settings", "owner": "Jordon Mingoes"})
