"""RentSettingsService (US-02) - owner: Jordon Mingoes

set_rent: validate amount and due day (AC-2), save a new RentSetting that
starts from the NEXT rent period (AC-4), so earlier periods keep old rent.
"""


def set_rent(*, shop, weekly_rent, due_day, set_by):
    raise NotImplementedError


def pending_rent_notices(user):
    """Rent changes this user should be told about at login (AC-5)."""
    raise NotImplementedError
