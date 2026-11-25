"""US-07 Payment receipts on WhatsApp - owner: Jordon Mingoes"""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, render

from rent.access import ensure_own_contractor, ensure_same_shop, role_required
from rent.models import Receipt, Role
from rent.services import receipts as receipt_service
from rent.services.contractors import shop_for


@role_required(Role.SHOP_SUPERVISOR)
def receipts(request):
    """The Shop Supervisor's receipts for their own shop."""
    shop = request.user.supervised_shop
    rows = [receipt_service.receipt_details(
        r) for r in receipt_service.receipts_for_shop(shop)]
    return render(request, "rent/receipts.html", {"shop": shop, "rows": rows})


@login_required
def receipt_detail(request, receipt_id):
    """One receipt. A Shop Supervisor opens their shop's; a contractor only their own (AC-5)."""
    receipt = get_object_or_404(
        Receipt.objects.select_related(
            "payment__contractor__shop", "payment__rent_period"),
        pk=receipt_id,
    )
    contractor = receipt.payment.contractor
    user = request.user
    if user.role == Role.SHOP_SUPERVISOR:
        ensure_same_shop(user, shop_for(contractor, receipt.payment.rent_period))
        can_send = True
    elif user.role == Role.CONTRACTOR:
        ensure_own_contractor(user, contractor)
        can_send = False
    else:
        raise PermissionDenied("Your role cannot open receipts.")
    return render(request, "rent/receipt_detail.html", {
        "d": receipt_service.receipt_details(receipt),
        "can_send": can_send,
        "link": receipt_service.whatsapp_link(receipt) if can_send else None,
    })
