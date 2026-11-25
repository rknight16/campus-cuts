"""ReceiptService (US-07) - owner: Jordon Mingoes

Creates numbered receipts (Receipt.number), marks corrected ones (AC-4) and
builds the WhatsApp click-to-chat link: https://wa.me/1876XXXXXXX?text=...
The system never sends anything itself (AC-2).
"""
from urllib.parse import quote

from rent.formatting import format_money
from rent.models import Receipt
from rent.services import rent_rules


def create_receipt(payment, *, corrects=None):
    """Save a receipt for `payment` with the balance still owed right now (AC-1).

    Call it inside the transaction that saves the payment or its correction.
    A receipt for a corrected payment is marked "Corrected" and points at the
    receipt it replaces (AC-4).
    """
    balance = rent_rules.balance(payment.contractor, payment.rent_period)
    return Receipt.objects.create(
        payment=payment,
        balance_after=balance if balance is not None else rent_rules.ZERO,
        is_corrected=corrects is not None or payment.is_corrected,
        corrects=corrects,
    )


def latest_receipt(payment):
    """The newest receipt for a payment, or None."""
    return payment.receipts.order_by("-created_at", "-pk").first()


def receipts_for_shop(shop, limit=50):
    """Newest receipts for a shop's contractors."""
    return list(
        Receipt.objects.filter(payment__contractor__shop=shop)
        .select_related("payment__contractor", "payment__rent_period", "payment__recorded_by", "corrects")
        .order_by("-created_at", "-pk")[:limit]
    )


def receipt_details(receipt):
    """What this receipt shows (AC-1).

    A correction overwrites the payment's amount and date, so the figures for an
    older receipt are rebuilt from the correction history as it was when the
    receipt was made. The original receipt keeps showing the original amount.
    """
    payment = receipt.payment
    corrections = list(payment.corrections.order_by("corrected_at"))
    made_before = [
        c for c in corrections if c.corrected_at <= receipt.created_at]
    if made_before:
        last = made_before[-1]
        amount, payment_date, received_by = last.new_amount, last.new_payment_date, last.corrected_by
    elif corrections:
        first = corrections[0]
        amount, payment_date, received_by = first.old_amount, first.old_payment_date, payment.recorded_by
    else:
        amount, payment_date, received_by = payment.amount, payment.payment_date, payment.recorded_by
    contractor = payment.contractor
    return {
        "receipt": receipt,
        "number": receipt.number,
        "shop": contractor.shop,
        "contractor": contractor,
        "period": payment.rent_period,
        "amount": amount,
        "balance": receipt.balance_after,
        "payment_date": payment_date,
        "received_by": received_by,
        "is_corrected": receipt.is_corrected,
        "corrects_number": receipt.corrects.number if receipt.corrects_id else None,
    }


def _date(d):
    return f"{d.day} {d:%b %Y}"  # not %-d, which crashes on Windows


def receipt_text(receipt):
    """The receipt as plain text, ready to be typed into WhatsApp."""
    d = receipt_details(receipt)
    lines = [f"CAMPUS CUTS RENT RECEIPT {d['number']}"]
    if d["is_corrected"]:
        replaces = f" (replaces receipt {d['corrects_number']})" if d["corrects_number"] else ""
        lines.append(f"CORRECTED{replaces}")
    lines += [
        f"Shop: {d['shop']}",
        f"Contractor: {d['contractor'].full_name} ({d['contractor'].staff_id})",
        f"Rent period: {d['period']}",
        f"Amount paid: {format_money(d['amount'])}",
        f"Balance still owed: {format_money(d['balance'])}",
        f"Payment date: {_date(d['payment_date'])}",
        f"Received by: {d['received_by']}",
    ]
    return "\n".join(lines)


def _whatsapp_number(phone):
    """Digits only, with Jamaica's country code added when it is missing."""
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if not digits:
        return None
    if len(digits) == 7:
        digits = "1876" + digits
    elif len(digits) == 10:
        digits = "1" + digits
    return digits


def whatsapp_link(receipt):
    """Return the wa.me URL, or None if the contractor has no phone (AC-3)."""
    number = _whatsapp_number(receipt.payment.contractor.phone)
    if number is None:
        return None
    return f"https://wa.me/{number}?text={quote(receipt_text(receipt), safe='')}"
