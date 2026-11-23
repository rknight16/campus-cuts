"""
python manage.py seed

Loads the same demo data on every team member's machine:
- the 5 Campus Cuts shops with their real weekly rent (SRS 1.1)
- 17 independent contractors (12 barbers, 3 hairstylists, 2 nail techs), 3-5 per shop
- one Shop Supervisor per shop, one Company Supervisor, the Owner
- one commission contractor at the Students' Union (for US-01 AC-6)
- payments for LAST week's rent period, mostly paid, a couple short (for dashboard/overdue)

Names and phone numbers are made up. Running it again wipes and reloads the data.
Every demo login uses the password in DEMO_PASSWORD.
"""
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.utils import timezone

from rent.models import (Campus, Contractor, PayType, Payment, RentPeriod,
                         RentSetting, Role, Shop, Trade, User, Weekday)

DEMO_PASSWORD = "campuscuts2026"

SHOPS = [  # name, campus, weekly rent (SRS 1.1)
    ("UWI Taylor Hall", Campus.UWI, 15000),
    ("UWI Towers Salon", Campus.UWI, 15000),
    ("UWI Students' Union", Campus.UWI, 18000),
    ("UTech Barbershop", Campus.UTECH, 12000),
    ("UTech Salon", Campus.UTECH, 12000),
]

# shop index, first, last, trade, pay type, supervisor?
CONTRACTORS = [
    (0, "Andre", "Campbell", Trade.BARBER, PayType.WEEKLY_RENT, True),
    (0, "Kemar", "Brown", Trade.BARBER, PayType.WEEKLY_RENT, False),
    (0, "Jason", "Thompson", Trade.BARBER, PayType.WEEKLY_RENT, False),
    (1, "Shanice", "Williams", Trade.HAIRSTYLIST, PayType.WEEKLY_RENT, True),
    (1, "Tanisha", "Reid", Trade.HAIRSTYLIST, PayType.WEEKLY_RENT, False),
    (1, "Kimone", "Gordon", Trade.NAIL_TECH, PayType.WEEKLY_RENT, False),
    (2, "Romario", "Clarke", Trade.BARBER, PayType.WEEKLY_RENT, True),
    (2, "Dwayne", "Henry", Trade.BARBER, PayType.WEEKLY_RENT, False),
    (2, "Shamar", "Lewis", Trade.BARBER, PayType.WEEKLY_RENT, False),
    (2, "Rushane", "Morgan", Trade.BARBER, PayType.WEEKLY_RENT, False),
    (2, "Javane", "Francis", Trade.BARBER, PayType.COMMISSION, False),
    (3, "Odane", "Grant", Trade.BARBER, PayType.WEEKLY_RENT, True),
    (3, "Tyrese", "Walker", Trade.BARBER, PayType.WEEKLY_RENT, False),
    (3, "Damion", "Allen", Trade.BARBER, PayType.WEEKLY_RENT, False),
    (4, "Abigail", "Johnson", Trade.HAIRSTYLIST, PayType.WEEKLY_RENT, True),
    (4, "Crystal", "Bailey", Trade.NAIL_TECH, PayType.WEEKLY_RENT, False),
    (4, "Kevin", "Smith", Trade.BARBER, PayType.WEEKLY_RENT, False),
]

# Last week's payments: everyone paid in full except these (staff index -> amount paid)
SHORT_PAYERS = {2: Decimal("10000"), 9: Decimal("0"), 13: Decimal("6000")}


class Command(BaseCommand):
    help = "Wipe and load the shared demo data (shops, contractors, logins, last week's payments)."

    @transaction.atomic
    def handle(self, *args, **options):
        self._wipe()
        today = timezone.localdate()
        current = RentPeriod.for_date(today)
        last_week = RentPeriod.for_date(today - timedelta(days=7))
        # Settings start last week, the first week with payments. Starting any
        # earlier would make every contractor overdue for weeks with no payments.
        start = last_week

        owner = self._user("owner", "Terron", "Dewar", Role.OWNER)
        self._user("company", "Marlon", "Edwards", Role.COMPANY_SUPERVISOR)

        shops = []
        for name, campus, rent in SHOPS:
            shop = Shop.objects.create(name=name, campus=campus)
            RentSetting.objects.create(
                shop=shop, weekly_rent=Decimal(rent), due_day=Weekday.FRIDAY,
                effective_from=start, created_by=owner,
            )
            shops.append(shop)

        contractors = []
        for i, (shop_i, first, last, trade, pay_type, is_sup) in enumerate(CONTRACTORS):
            staff_id = f"{1001 + i}"
            role = Role.SHOP_SUPERVISOR if is_sup else Role.CONTRACTOR
            username = f"sup{shop_i + 1}" if is_sup else f"c{staff_id}"
            user = self._user(username, first, last, role)
            c = Contractor.objects.create(
                user=user, full_name=f"{first} {last}", staff_id=staff_id, shop=shops[shop_i],
                trade=trade, pay_type=pay_type,
                phone="" if i == 16 else f"876-555-{100 + i:04d}",  # one with no phone (US-07 AC-3)
            )
            if is_sup:
                shops[shop_i].supervisor = c
                shops[shop_i].save()
            contractors.append(c)

        # Last week's payments, recorded by each shop's supervisor, paid on the Friday
        paid_on = last_week.due_date_for(Weekday.FRIDAY)
        for i, c in enumerate(contractors):
            if c.pay_type == PayType.COMMISSION:
                continue  # commission owed depends on earnings - left for US-01 to demo
            rent = RentSetting.for_shop(c.shop, last_week).weekly_rent
            amount = SHORT_PAYERS.get(i, rent)
            if amount > 0:
                Payment.objects.create(
                    contractor=c, rent_period=last_week, amount=amount,
                    payment_date=paid_on, recorded_by=c.shop.supervisor.user,
                )

        self.stdout.write(self.style.SUCCESS(
            f"Loaded {len(shops)} shops, {len(contractors)} contractors, "
            f"{Payment.objects.count()} payments for {last_week}. Current period: {current}."
        ))
        self.stdout.write("Logins (password for all: %s):" % DEMO_PASSWORD)
        self.stdout.write("  owner         Owner (Terron Dewar)")
        self.stdout.write("  company       Company Supervisor")
        for n, s in enumerate(shops, 1):
            self.stdout.write(f"  sup{n}          Shop Supervisor, {s.name}")
        self.stdout.write("  c1002         Independent contractor (Kemar Brown, Taylor Hall)")
        self.stdout.write("  c1011         Contractor on commission (Students' Union)")

    def _user(self, username, first, last, role):
        u = User(username=username, first_name=first, last_name=last, role=role,
                 is_staff=(role == Role.OWNER), is_superuser=(role == Role.OWNER))
        u.set_password(DEMO_PASSWORD)
        u.save()
        return u

    def _wipe(self):
        # Payments and handoffs refuse .delete() (SF-1), so the demo reset
        # empties the tables directly. Never do this outside the seed command.
        tables = [
            "rent_receipt", "rent_paymentcorrection", "rent_payment", "rent_handoff",
            "rent_commissionearning", "rent_rentsetting", "rent_shop", "rent_contractor",
            "rent_rentperiod",
        ]
        with connection.cursor() as cur:
            cur.execute("TRUNCATE %s RESTART IDENTITY CASCADE" % ", ".join(tables))
        User.objects.all().delete()
