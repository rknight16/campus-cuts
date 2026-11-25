"""
python manage.py seed

Loads the same demo data on every team member's machine, so every feature has something to show:
- the 5 Campus Cuts shops with their real weekly rent (SRS 1.1), set from two weeks ago
- 17 independent contractors (12 barbers, 3 hairstylists, 2 nail techs), 3-5 per shop
- one Shop Supervisor per shop, one Company Supervisor, the Owner
- three weeks of rent (two weeks ago, last week, this week), recorded through the payment
  service so every payment has its receipt (US-01, US-07):
    two weeks ago: everyone paid in full
    last week: everyone paid except three short payers, who are overdue (US-04 AC-2, US-06 AC-2)
    this week: a mix of paid, part-paid and not paid yet
- Kemar Brown (c1002) has four payments for a payment history (US-06 AC-3)
- Damion Allen's last-week payment was corrected with a reason, so it has a Corrected receipt (US-01 AC-7, US-07 AC-4)
- Javane Francis (c1011) is on commission with earnings entered for past weeks, none yet this week (US-01 AC-6)
- handoffs: two weeks ago all confirmed and handed to the Owner (waiting for the Owner);
  last week one mismatch waiting for the Company Supervisor, two confirmed, one waiting, one not handed (US-03, US-04)
- Taylor Hall's rent goes up to $16,000 next week, so its users see a notice when they log in (US-02 AC-5)
- Rushane Morgan has left (deactivated) still owing last week's rent; Kevin Smith moves to the UTech Barbershop
  next week; Javane Francis moves to weekly rent next week (US-05 AC-3, AC-4, AC-6)
- Kevin Smith has no phone number, so his receipts show "phone number needed" (US-07 AC-3)

Names and phone numbers are made up. To get Kemar Brown's WhatsApp receipts on your own phone, put
DEMO_PHONE=876-xxx-xxxx in your .env (never commit it). Running it again wipes and reloads the data.
Every demo login uses the password in DEMO_PASSWORD.
"""
import os
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.utils import timezone

from rent.models import (Campus, Contractor, PayType, Payment, RentPeriod,
                         RentSetting, Role, Shop, Trade, User, Weekday)
from rent.services import contractors as contractor_service
from rent.services import handoffs as handoff_service
from rent.services import payments as payment_service
from rent.services import rent_settings

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
KEMAR, JASON, RUSHANE, JAVANE, DAMION, KEVIN = 1, 2, 9, 10, 13, 16

# Last week: everyone paid in full except these (staff index -> amount paid). Only these are overdue.
SHORT_PAYERS = {JASON: Decimal("10000"), RUSHANE: Decimal("0"), DAMION: Decimal("6000")}
# This week (not due until Friday): who has paid what so far
THIS_WEEK = {0: "15000", KEMAR: "10000", 3: "15000", 4: "7500", 6: "18000", 11: "12000", 14: "12000"}
# Commission earnings for Javane: two weeks ago, last week (40% is owed); none yet this week
JAVANE_EARNINGS = ("30000", "25000")


class Command(BaseCommand):
    help = "Wipe and load the shared demo data (shops, contractors, logins, three weeks of rent, handoffs)."

    @transaction.atomic
    def handle(self, *args, **options):
        self._wipe()
        today = timezone.localdate()
        current = RentPeriod.for_date(today)
        last_week = RentPeriod.for_date(today - timedelta(days=7))
        two_weeks = RentPeriod.for_date(today - timedelta(days=14))
        start = two_weeks  # rent and joining dates start here, the first week with payments

        owner = self._user("owner", "Terron", "Dewar", Role.OWNER)
        company = self._user("company", "Marlon", "Edwards", Role.COMPANY_SUPERVISOR)

        shops = []
        for name, campus, rent in SHOPS:
            shop = Shop.objects.create(name=name, campus=campus)
            RentSetting.objects.create(
                shop=shop, weekly_rent=Decimal(rent), due_day=Weekday.FRIDAY,
                effective_from=start, created_by=owner,
            )
            shops.append(shop)

        demo_phone = os.environ.get("DEMO_PHONE", "").strip()
        people = []
        for i, (shop_i, first, last, trade, pay_type, is_sup) in enumerate(CONTRACTORS):
            staff_id = f"{1001 + i}"
            role = Role.SHOP_SUPERVISOR if is_sup else Role.CONTRACTOR
            username = f"sup{shop_i + 1}" if is_sup else f"c{staff_id}"
            user = self._user(username, first, last, role)
            phone = "" if i == KEVIN else f"876-555-{100 + i:04d}"  # Kevin has none (US-07 AC-3)
            if i == KEMAR and demo_phone:
                phone = demo_phone
            c = Contractor.objects.create(
                user=user, full_name=f"{first} {last}", staff_id=staff_id, shop=shops[shop_i],
                trade=trade, pay_type=pay_type, phone=phone,
                joined_on=start.start_date,  # everyone has worked here since rent started (US-06 AC-2)
            )
            contractor_service.ensure_initial_assignment(c)  # shop and pay type history (US-05)
            if is_sup:
                shops[shop_i].supervisor = c
                shops[shop_i].save()
            people.append(c)

        def pay(c, period, amount, on):
            sup = c.shop.supervisor.user
            return payment_service.record_payment(
                contractor=c, period=period, amount=amount, payment_date=on, recorded_by=sup)

        def rent_for(c, period):
            return RentSetting.for_shop(c.shop, period).weekly_rent

        # Commission earnings first, so Javane's amount owed is known (US-01 AC-6)
        javane = people[JAVANE]
        for period, earnings in zip((two_weeks, last_week), JAVANE_EARNINGS):
            payment_service.enter_commission_earnings(
                contractor=javane, period=period, earnings=earnings, entered_by=javane.shop.supervisor.user)

        # Two weeks ago: everyone paid in full on the Friday
        for i, c in enumerate(people):
            owed = (Decimal(JAVANE_EARNINGS[0]) * Decimal("0.4")) if i == JAVANE else rent_for(c, two_weeks)
            pay(c, two_weeks, owed, two_weeks.due_date_for(Weekday.FRIDAY))

        # Last week: everyone in full except the short payers. Kemar paid in two parts (history);
        # Damion's payment was keyed in wrong and corrected (US-01 AC-7, US-07 AC-4).
        friday = last_week.due_date_for(Weekday.FRIDAY)
        for i, c in enumerate(people):
            owed = (Decimal(JAVANE_EARNINGS[1]) * Decimal("0.4")) if i == JAVANE else rent_for(c, last_week)
            amount = SHORT_PAYERS.get(i, owed)
            if i == KEMAR:
                pay(c, last_week, Decimal("10000"), friday)
                pay(c, last_week, owed - Decimal("10000"), friday + timedelta(days=1))
            elif i == DAMION:
                wrong = pay(c, last_week, Decimal("9000"), friday)
                payment_service.correct_payment(
                    payment=wrong, new_amount=amount, new_payment_date=friday,
                    reason="Typing error", corrected_by=c.shop.supervisor.user)
            elif amount > 0:
                pay(c, last_week, amount, friday)

        # This week so far (due Friday, so nobody is overdue for it yet)
        for i, amount in THIS_WEEK.items():
            on = min(today, current.start_date + timedelta(days=1 if i == KEMAR else 0))
            pay(people[i], current, Decimal(amount), on)

        # Handoffs. Two weeks ago: every shop handed over and was confirmed, then the Company Supervisor
        # handed the total to the Owner, who has not confirmed yet (the Owner's waiting strip).
        for shop in shops:
            h = handoff_service.record_shop_handoff(
                shop=shop, period=two_weeks, amount=handoff_service.expected_shop_amount(shop, two_weeks),
                handed_date=two_weeks.end_date, handed_by=shop.supervisor.user)
            handoff_service.confirm_handoff(handoff=h, amount_received=h.amount_handed, confirmed_by=company)
        handoff_service.record_owner_handoff(
            period=two_weeks, amount=handoff_service.expected_owner_amount(two_weeks),
            handed_date=last_week.start_date, handed_by=company)

        # Last week: Taylor Hall handed over $5,000 short (mismatch, waiting for the Company Supervisor);
        # Towers and UTech Barbershop confirmed; Students' Union waiting; UTech Salon not handed over yet.
        for shop_i, short, confirm in ((0, Decimal("5000"), False), (1, 0, True), (2, 0, False), (3, 0, True)):
            shop = shops[shop_i]
            h = handoff_service.record_shop_handoff(
                shop=shop, period=last_week, amount=handoff_service.expected_shop_amount(shop, last_week) - short,
                handed_date=min(today, last_week.end_date + timedelta(days=1)), handed_by=shop.supervisor.user)
            if confirm:
                handoff_service.confirm_handoff(handoff=h, amount_received=h.amount_handed, confirmed_by=company)

        # Next week's changes, made through the Owner's own services
        rent_settings.set_rent(shop=shops[0], weekly_rent="16000", due_day=Weekday.FRIDAY, set_by=owner)  # US-02 AC-5
        contractor_service.transfer(contractor=people[KEVIN], new_shop=shops[3])                          # US-05 AC-4
        contractor_service.change_pay_type(contractor=javane)                                             # US-05 AC-3
        contractor_service.deactivate(contractor=people[RUSHANE])                                         # US-05 AC-6

        self.stdout.write(self.style.SUCCESS(
            f"Loaded {len(shops)} shops, {len(people)} contractors, {Payment.objects.count()} payments "
            f"({two_weeks.start_date:%d %b} to {current.end_date:%d %b %Y}). Current period: {current}."
        ))
        if demo_phone:
            self.stdout.write("  Kemar Brown's receipts go to DEMO_PHONE from your .env.")
        self.stdout.write("Logins (password for all: %s):" % DEMO_PASSWORD)
        self.stdout.write("  owner         Owner (Terron Dewar) - handoff waiting, Taylor Hall rent change")
        self.stdout.write("  company       Company Supervisor - 2 shop handoffs waiting (one mismatch)")
        for n, s in enumerate(shops, 1):
            self.stdout.write(f"  sup{n}          Shop Supervisor, {s.name}")
        self.stdout.write("  c1002         Kemar Brown, Taylor Hall - payment history, WhatsApp receipts")
        self.stdout.write("  c1011         Javane Francis, commission (Students' Union)")
        self.stdout.write("  c1014         Damion Allen - corrected payment, overdue")

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
            "rent_commissionearning", "rent_shopassignment", "rent_rentsetting", "rent_shop",
            "rent_contractor", "rent_rentperiod",
        ]
        with connection.cursor() as cur:
            cur.execute("TRUNCATE %s RESTART IDENTITY CASCADE" % ", ".join(tables))
        User.objects.all().delete()
