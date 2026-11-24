"""Shared test data. Use make_world() in your own tests so everyone tests the same setup."""
from datetime import date
from decimal import Decimal

from rent.models import (Campus, Contractor, RentPeriod, RentSetting, Role,
                         Shop, User, Weekday)

PASSWORD = "testpass123"


def make_user(username, role):
    return User.objects.create_user(username=username, password=PASSWORD, role=role)


# The SRS scenarios start in the rent period 2 to 8 Nov 2026, so everyone in make_world() has worked
# there since then. Rent (and overdue, US-06 AC-2) only counts from the week a contractor joined.
SRS_FIRST_DAY = date(2026, 11, 2)


def make_contractor(username, staff_id, shop, role=Role.CONTRACTOR, joined_on=SRS_FIRST_DAY):
    user = make_user(username, role)
    return Contractor.objects.create(user=user, full_name=username.title(), staff_id=staff_id, shop=shop,
                                     joined_on=joined_on)


def make_world():
    """Two shops (Taylor Hall $15,000, UTech Barbershop $12,000, both due Friday),
    a supervisor and a contractor at each, plus the Owner and Company Supervisor.
    Rent period used in the SRS scenarios: 2 to 8 November 2026."""
    w = type("World", (), {})()
    w.period = RentPeriod.for_date(date(2026, 11, 2))
    w.owner = make_user("owner", Role.OWNER)
    w.company = make_user("company", Role.COMPANY_SUPERVISOR)
    w.taylor = Shop.objects.create(name="UWI Taylor Hall", campus=Campus.UWI)
    w.utech = Shop.objects.create(name="UTech Barbershop", campus=Campus.UTECH)
    for shop, rent in ((w.taylor, 15000), (w.utech, 12000)):
        RentSetting.objects.create(shop=shop, weekly_rent=Decimal(rent), due_day=Weekday.FRIDAY,
                                   effective_from=w.period, created_by=w.owner)
    w.taylor_sup = make_contractor("taylorsup", "1001", w.taylor, Role.SHOP_SUPERVISOR)
    w.utech_sup = make_contractor("utechsup", "2001", w.utech, Role.SHOP_SUPERVISOR)
    w.taylor.supervisor = w.taylor_sup; w.taylor.save()
    w.utech.supervisor = w.utech_sup; w.utech.save()
    w.taylor_c = make_contractor("taylorc", "1002", w.taylor)
    w.utech_c = make_contractor("utechc", "2002", w.utech)
    return w
