from datetime import date
from decimal import Decimal

from django.test import TestCase

from rent.models import Handoff, HandoffStatus, HandoffStep, Payment
from rent.services import dashboard
from rent.tests.helpers import make_contractor, make_world
from unittest.mock import patch

from django.urls import reverse

NOV_4 = date(2026, 11, 4)   # Wednesday, before the due date
NOV_7 = date(2026, 11, 7)   # Saturday, after the Friday due day


def row_for(result, shop):
    return next(r for r in result["shops"] if r["shop"] == shop)


class DashboardServiceTests(TestCase):
    def setUp(self):
        self.w = make_world()
        # make_world gives Taylor Hall two contractors, the SRS scenario has three
        self.taylor3 = make_contractor("taylor3", "1003", self.w.taylor)
        # UTech Barbershop gets a third one too: 3 x $12,000 = $36,000
        self.utech3 = make_contractor("utech3", "2003", self.w.utech)

    def pay(self, contractor, amount):
        return Payment.objects.create(
            contractor=contractor, rent_period=self.w.period, amount=Decimal(amount),
            payment_date=date(2026, 11, 3), recorded_by=self.w.taylor_sup.user)

    def test_ac1_owner_views_dashboard_before_due_date(self):
        self.pay(self.w.taylor_sup, "15000")
        self.pay(self.w.taylor_c, "15000")
        taylor = row_for(dashboard.shop_summary(today=NOV_4), self.w.taylor)
        self.assertEqual(taylor["owed"], Decimal("45000"))
        self.assertEqual(taylor["paid"], Decimal("30000"))
        self.assertEqual(taylor["balance"], Decimal("15000"))
        self.assertEqual(taylor["overdue"], Decimal("0"))

    def test_ac1_totals_cover_all_shops(self):
        self.pay(self.w.taylor_sup, "15000")
        totals = dashboard.shop_summary(today=NOV_4)["totals"]
        self.assertEqual(totals["owed"], Decimal("81000"))     # 45,000 + 36,000
        self.assertEqual(totals["paid"], Decimal("15000"))
        self.assertEqual(totals["balance"], Decimal("66000"))

    def test_ac2_unpaid_rent_becomes_overdue(self):
        self.pay(self.w.taylor_sup, "15000")
        self.pay(self.w.taylor_c, "15000")
        taylor = row_for(dashboard.shop_summary(today=NOV_7), self.w.taylor)
        self.assertEqual(taylor["overdue"], Decimal("15000"))

    def test_ac3_dashboard_shows_handoff_mismatch(self):
        Handoff.objects.create(
            step=HandoffStep.SHOP_TO_COMPANY, shop=self.w.taylor, rent_period=self.w.period,
            expected_amount=Decimal("30000"), amount_handed=Decimal("29000"),
            handed_date=date(2026, 11, 3), handed_by=self.w.taylor_sup.user)
        taylor = row_for(dashboard.shop_summary(today=NOV_4), self.w.taylor)
        self.assertTrue(taylor["handoff"].is_mismatch)
        self.assertEqual(taylor["handoff"].expected_amount, Decimal("30000"))
        self.assertEqual(taylor["handoff"].amount_handed, Decimal("29000"))

    def test_uc04_a2_shop_with_no_handoff_is_not_yet_handed_over(self):
        utech = row_for(dashboard.shop_summary(today=NOV_4), self.w.utech)
        self.assertIsNone(utech["handoff"])

    def test_ac4_shop_with_no_payments_is_still_listed(self):
        utech = row_for(dashboard.shop_summary(today=NOV_4), self.w.utech)
        self.assertEqual(utech["owed"], Decimal("36000"))
        self.assertEqual(utech["paid"], Decimal("0"))
        self.assertEqual(utech["balance"], Decimal("36000"))


class DashboardPageTests(TestCase):
    def setUp(self):
        patcher = patch("django.utils.timezone.localdate", return_value=NOV_4)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.w = make_world()
        self.url = reverse("dashboard")

    def test_ac5_owner_can_open_dashboard(self):
        self.client.force_login(self.w.owner)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "UWI Taylor Hall")

    def test_ac5_company_supervisor_can_open_dashboard(self):
        self.client.force_login(self.w.company)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_ac5_shop_supervisor_is_denied(self):
        self.client.force_login(self.w.taylor_sup.user)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_ac5_contractor_is_denied(self):
        self.client.force_login(self.w.taylor_c.user)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_ac5_logged_out_user_is_sent_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_ac4_page_lists_every_shop_even_with_nothing_paid(self):
        self.client.force_login(self.w.owner)
        response = self.client.get(self.url)
        self.assertContains(response, "UTech Barbershop")
        self.assertContains(response, "Not yet handed over")

    def test_ac3_page_shows_mismatch_flag(self):
        Handoff.objects.create(
            step=HandoffStep.SHOP_TO_COMPANY, shop=self.w.taylor, rent_period=self.w.period,
            expected_amount=Decimal("30000"), amount_handed=Decimal("29000"),
            handed_date=date(2026, 11, 3), handed_by=self.w.taylor_sup.user)
        self.client.force_login(self.w.owner)
        self.assertContains(self.client.get(self.url), "Mismatch")