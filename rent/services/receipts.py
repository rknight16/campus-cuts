"""ReceiptService (US-07) - owner: Jordon Mingoes

Creates numbered receipts (Receipt.number), marks corrected ones (AC-4) and
builds the WhatsApp click-to-chat link: https://wa.me/1876XXXXXXX?text=...
The system never sends anything itself (AC-2).
"""


def create_receipt(payment, *, corrects=None):
    raise NotImplementedError


def whatsapp_link(receipt):
    """Return the wa.me URL, or None if the contractor has no phone (AC-3)."""
    raise NotImplementedError
