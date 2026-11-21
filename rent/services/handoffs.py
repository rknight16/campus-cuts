"""HandoffService (US-03) - owner: Chiantina Lawrence

Shop -> Company Supervisor: expected = payments at the shop with payment_date
in the period (AC-2). Company Supervisor -> Owner: expected = total the CS
confirmed from the shops (AC-4). Mismatch flag is Handoff.is_mismatch (AC-5).
"""


def record_shop_handoff(*, shop, period, amount, handed_date, handed_by):
    raise NotImplementedError


def record_owner_handoff(*, period, amount, handed_date, handed_by):
    raise NotImplementedError


def confirm_handoff(*, handoff, amount_received, confirmed_by):
    raise NotImplementedError
