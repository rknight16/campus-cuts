"""US-06 View my rent, due date and payment history - owner: Raynardo Knight

Presentation layer only (SDS 2.3.1): the figures come from rent_rules.account_overview().
Viewing the page changes nothing (UC-06 post-condition).
"""
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, render

from rent.access import contractor_required, ensure_own_contractor
from rent.models import Contractor, Receipt
from rent.services import rent_rules


def _account_page(request, contractor):
    payments = (
        contractor.payments.select_related("rent_period")  # newest first (Payment.Meta.ordering), AC-3
        .prefetch_related("corrections", Prefetch("receipts", queryset=Receipt.objects.order_by("-created_at")))
    )
    overview = rent_rules.account_overview(contractor)
    return render(request, "rent/my_account.html", {
        "contractor": contractor,
        "rent": overview,
        "payments": payments,
        # Receipts arrive with US-07; the column only appears once one exists.
        "has_receipts": Receipt.objects.filter(payment__contractor=contractor).exists(),
    })


@contractor_required
def my_account(request):
    return _account_page(request, request.user.contractor_profile)


@contractor_required
def contractor_account(request, contractor_id):
    """Same page by ID. Anyone other than the contractor gets 403 (AC-4)."""
    contractor = get_object_or_404(Contractor, pk=contractor_id)
    ensure_own_contractor(request.user, contractor)
    return _account_page(request, contractor)
