"""US-06 View my rent, due date and payment history - owner: Raynardo Knight"""
from django.shortcuts import get_object_or_404, render

from rent.access import contractor_required, ensure_own_contractor
from rent.models import Contractor, RentPeriod


@contractor_required
def my_account(request):
    contractor = request.user.contractor_profile
    return render(request, "rent/my_account.html", {
        "contractor": contractor,
        "period": RentPeriod.current(),
        "payments": contractor.payments.select_related("rent_period"),
    })


@contractor_required
def contractor_account(request, contractor_id):
    """Same page by ID. Anyone other than the contractor gets 403 (AC-4)."""
    contractor = get_object_or_404(Contractor, pk=contractor_id)
    ensure_own_contractor(request.user, contractor)
    return render(request, "rent/my_account.html", {
        "contractor": contractor,
        "period": RentPeriod.current(),
        "payments": contractor.payments.select_related("rent_period"),
    })
