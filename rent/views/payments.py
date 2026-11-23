"""US-01 Record rent payments - owner: Raynardo Knight

Views only read the form, call rent.services.payments and show the result.
Every view checks the role, and every contractor/payment taken from the URL or
form is checked with ensure_same_shop (AC-5), so typing another shop's ID
gives 403.
"""
from urllib.parse import urlencode

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from rent.access import contractors_visible_to, ensure_same_shop, role_required
from rent.formatting import format_money
from rent.models import Contractor, PayType, Payment, RentPeriod, Role
from rent.services import payments as payment_service
from rent.services import rent_rules

PERIODS_SHOWN = 8  # current period and the 7 before it


def _recent_periods():
    current = RentPeriod.current()
    return list(RentPeriod.objects.filter(start_date__lte=current.start_date)
                .order_by("-start_date")[:PERIODS_SHOWN])


def _get_or_404(model, raw_id):
    try:
        return get_object_or_404(model, pk=int(raw_id))
    except (TypeError, ValueError):
        raise Http404


def _record_url(contractor, period):
    return reverse("record_payment") + "?" + urlencode({"contractor": contractor.pk, "period": period.pk})


@role_required(Role.SHOP_SUPERVISOR)
def record_payment(request):
    """Pick contractor and period, see owed/paid/balance, record a payment (AC-1 to AC-6)."""
    data = request.POST if request.method == "POST" else request.GET

    contractor = None
    if data.get("contractor"):
        contractor = _get_or_404(Contractor.objects.select_related("shop"), data["contractor"])
        ensure_same_shop(request.user, contractor.shop)  # typed URL for another shop -> 403
    period = _get_or_404(RentPeriod, data["period"]) if data.get("period") else RentPeriod.current()

    error = None
    if request.method == "POST" and contractor is not None:
        action = request.POST.get("action")
        try:
            if action == "earnings":
                earning = payment_service.enter_commission_earnings(
                    contractor=contractor, period=period,
                    earnings=request.POST.get("earnings"), entered_by=request.user,
                )
                messages.success(request, (
                    f"Earnings saved: {format_money(earning.earnings)}. "
                    f"{contractor.full_name} owes {format_money(rent_rules.amount_owed(contractor, period))} (40%)."
                ))
                return redirect(_record_url(contractor, period))
            if action == "payment":
                payment = payment_service.record_payment(
                    contractor=contractor, period=period, amount=request.POST.get("amount"),
                    payment_date=request.POST.get("payment_date"), recorded_by=request.user,
                )
                s = rent_rules.summary(contractor, period)
                text = f"Saved {format_money(payment.amount)} from {contractor.full_name}. Status: {s['status']}."
                if s["balance"]:
                    text += f" {format_money(s['balance'])} still owed."
                messages.success(request, text)  # AC-4
                return redirect(_record_url(contractor, period))
            error = "Something went wrong with that form. Please try again."
        except ValidationError as e:
            error = " ".join(e.messages)  # nothing was saved

    context = {
        "contractors": contractors_visible_to(request.user).order_by("-is_active", "full_name"),
        "periods": _recent_periods(),
        "contractor": contractor,
        "period": period,
        "error": error,
        "today": timezone.localdate(),
        "form": request.POST if request.method == "POST" else {},
    }
    if contractor is not None:
        context.update({
            "summary": rent_rules.summary(contractor, period),
            "is_commission": contractor.pay_type == PayType.COMMISSION,
            "earning": rent_rules.commission_earnings(contractor, period),
            "period_payments": contractor.payments.filter(rent_period=period)
                                         .select_related("recorded_by").prefetch_related("corrections"),
        })
    return render(request, "rent/record_payment.html", context)


@role_required(Role.SHOP_SUPERVISOR)
def correct_payment(request, payment_id):
    """Correct a payment's amount or date with a reason; the original is kept (AC-7)."""
    payment = get_object_or_404(Payment.objects.select_related("contractor__shop", "rent_period"), pk=payment_id)
    ensure_same_shop(request.user, payment.contractor.shop)  # typed URL for another shop -> 403

    error = None
    if request.method == "POST":
        old_amount = payment.amount
        try:
            payment = payment_service.correct_payment(
                payment=payment, new_amount=request.POST.get("amount"),
                new_payment_date=request.POST.get("payment_date"),
                reason=request.POST.get("reason"), corrected_by=request.user,
            )
            s = rent_rules.summary(payment.contractor, payment.rent_period)
            text = (f"Payment corrected from {format_money(old_amount)} to {format_money(payment.amount)}. "
                    f"Status: {s['status']}.")
            if s["balance"]:
                text += f" {format_money(s['balance'])} still owed."
            messages.success(request, text)
            return redirect(_record_url(payment.contractor, payment.rent_period))
        except ValidationError as e:
            error = " ".join(e.messages)

    return render(request, "rent/correct_payment.html", {
        "payment": payment,
        "corrections": payment.corrections.select_related("corrected_by"),
        "summary": rent_rules.summary(payment.contractor, payment.rent_period),
        "error": error,
        "today": timezone.localdate(),
        "form": request.POST if request.method == "POST" else {},
    })
