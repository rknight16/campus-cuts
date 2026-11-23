"""Tests for the shared base: rent periods, rent settings, deletion guard, access control."""
from datetime import date
from decimal import Decimal
from io import StringIO

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from rent.models import (Contractor, Handoff, HandoffStep, Payment, RentPeriod,
                         RentSetting, Role, Shop, User, Weekday)

from .helpers import PASSWORD, make_world


class RentPeriodTests(TestCase):
    def test_period_runs_monday_to_sunday(self):
        p = RentPeriod.for_date(date(2026, 11, 4))  # a Wednesday
        self.assertEqual(p.start_date, date(2026, 11, 2))
        self.assertEqual(p.end_date, date(2026, 11, 8))

    def test_same_period_reused(self):
        self.assertEqual(RentPeriod.for_date(date(2026, 11, 2)), RentPeriod.for_date(date(2026, 11, 8)))

    def test_due_date_friday(self):  # SRS US-02 AC-3 scenario
        p = RentPeriod.for_date(date(2026, 11, 2))
        self.assertEqual(p.due_date_for(Weekday.FRIDAY), date(2026, 11, 6))


class RentSettingTests(TestCase):
    def test_earlier_period_keeps_old_rent(self):  # SRS US-02 AC-4 scenario
        w = make_world()
        nxt = w.period.next()
        RentSetting.objects.create(shop=w.taylor, weekly_rent=Decimal("16000"),
                                   due_day=Weekday.FRIDAY, effective_from=nxt)
        self.assertEqual(RentSetting.for_shop(w.taylor, w.period).weekly_rent, Decimal("15000"))
        self.assertEqual(RentSetting.for_shop(w.taylor, nxt).weekly_rent, Decimal("16000"))


class DeletionGuardTests(TestCase):
    """SF-1: payments and handoffs are never deleted."""
    def setUp(self):
        self.w = make_world()
        self.payment = Payment.objects.create(contractor=self.w.taylor_c, rent_period=self.w.period,
                                              amount=Decimal("15000"), payment_date=date(2026, 11, 6),
                                              recorded_by=self.w.taylor_sup.user)

    def test_payment_cannot_be_deleted(self):
        with self.assertRaises(PermissionDenied):
            self.payment.delete()
        with self.assertRaises(PermissionDenied):
            Payment.objects.all().delete()
        self.assertEqual(Payment.objects.count(), 1)

    def test_handoff_cannot_be_deleted(self):
        h = Handoff.objects.create(step=HandoffStep.SHOP_TO_COMPANY, shop=self.w.taylor,
                                   rent_period=self.w.period, expected_amount=Decimal("15000"),
                                   amount_handed=Decimal("15000"), handed_date=date(2026, 11, 8),
                                   handed_by=self.w.taylor_sup.user)
        with self.assertRaises(PermissionDenied):
            h.delete()

    def test_mismatch_flag(self):  # US-03 AC-5 scenario
        h = Handoff(expected_amount=Decimal("45000"), amount_handed=Decimal("40000"))
        self.assertTrue(h.is_mismatch)


class StaffIdTests(TestCase):
    def test_staff_id_must_be_4_digits(self):
        w = make_world()
        c = Contractor(user=User.objects.create_user("x", password=PASSWORD), full_name="X",
                       staff_id="123", shop=w.taylor)
        with self.assertRaises(ValidationError):
            c.full_clean()


class AccessTests(TestCase):
    """SE-2: the server checks the role on every request, even typed URLs."""
    def setUp(self):
        self.w = make_world()

    def login(self, user):
        self.client.login(username=user.username, password=PASSWORD)

    def test_must_log_in(self):
        r = self.client.get(reverse("dashboard"))
        self.assertRedirects(r, reverse("login") + "?next=" + reverse("dashboard"))

    def test_each_role_lands_on_own_home(self):
        cases = [(self.w.owner, "owner_home"), (self.w.company, "company_home"),
                 (self.w.taylor_sup.user, "supervisor_home"), (self.w.taylor_c.user, "my_account")]
        for user, url in cases:
            self.login(user)
            self.assertRedirects(self.client.get(reverse("home")), reverse(url))

    def test_dashboard_owner_and_company_only(self):  # US-04 AC-5
        for user, code in [(self.w.owner, 200), (self.w.company, 200),
                           (self.w.taylor_sup.user, 403), (self.w.taylor_c.user, 403)]:
            self.login(user)
            self.assertEqual(self.client.get(reverse("dashboard")).status_code, code, user)

    def test_supervisor_sees_only_own_shop(self):  # US-01 AC-5
        self.login(self.w.taylor_sup.user)
        r = self.client.get(reverse("supervisor_home"))
        self.assertContains(r, self.w.taylor_c.full_name)
        self.assertNotContains(r, self.w.utech_c.full_name)

    def test_contractor_cannot_open_someone_elses_account(self):  # US-06 AC-4
        self.login(self.w.taylor_c.user)
        own = reverse("contractor_account", args=[self.w.taylor_c.pk])
        other = reverse("contractor_account", args=[self.w.utech_c.pk])
        self.assertEqual(self.client.get(own).status_code, 200)
        self.assertEqual(self.client.get(other).status_code, 403)

    def test_owner_only_pages(self):
        for name in ("contractors", "rent_settings"):
            self.login(self.w.taylor_sup.user)
            self.assertEqual(self.client.get(reverse(name)).status_code, 403)
            self.login(self.w.owner)
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)


class SeedTests(TestCase):
    def test_seed_loads_demo_data(self):
        call_command("seed", stdout=StringIO())
        self.assertEqual(Shop.objects.count(), 5)
        self.assertEqual(Contractor.objects.count(), 17)
        self.assertEqual(Shop.objects.filter(supervisor__isnull=False).count(), 5)
        self.assertEqual(User.objects.filter(role=Role.OWNER).count(), 1)
        self.assertEqual(User.objects.filter(role=Role.COMPANY_SUPERVISOR).count(), 1)
        self.assertTrue(self.client.login(username="sup1", password="campuscuts2026"))
