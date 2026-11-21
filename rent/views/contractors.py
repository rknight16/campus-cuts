"""US-05 Manage contractors and shop assignments - owner: Jordon Stewart"""
from django.shortcuts import render

from rent.access import role_required
from rent.models import Role


@role_required(Role.OWNER)
def contractors(request):
    # TODO: build this page. Call rent.services.contractors for the rules.
    return render(request, "rent/placeholder.html", {"title": "Manage contractors", "owner": "Jordon Stewart"})
