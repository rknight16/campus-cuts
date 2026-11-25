"""Owner and Company Supervisor homes: each shop's week in money, and what is waiting for them."""
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from rent.models import Handoff, HandoffStatus, HandoffStep, Payment, RentPeriod
from rent.tests.helpers import make_contractor, make_world

TODAY = date(2026, 11, 11)  # Wednesday of the week after the SRS period (2 to 8 Nov 2026)


class ShopHomeTests(TestCase):
    def setUp(self):
        patcher = patch("django.utils.timezone.localdate", return_value=TODAY)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.w = make_world()
        self.this_week = RentPeriod.current()
        Payment.objects.create(contractor=self.w.taylor_c, rent_period=self.this_week, amount=Decimal("5000"),
                               payment_date=TODAY, recorded_by=self.w.taylor_sup.user)

    def card(self, response, shop):
        return next(c for c in response.context["cards"] if c["shop"] == shop)

    def test_cards_show_collected_outstanding_and_overdue(self):
        self.client.force_login(self.w.owner)
        response = self.client.get(reverse("owner_home"))
        taylor = self.card(response, self.w.taylor)
        self.assertEqual(taylor["collected"], Decimal("5000"))
        self.assertEqual(taylor["outstanding"], Decimal("25000"))  # 2 x $15,000 less the $5,000 paid
        self.assertEqual(taylor["overdue"], Decimal("30000"))      # nobody paid last week (due Fri 6 Nov)
        self.assertEqual(response.context["collected"], Decimal("5000"))
        self.assertContains(response, "Collected this week")

    def test_deactivated_contractors_unpaid_rent_stays_overdue(self):
        """US-05 AC-6: someone who left on Sun 8 Nov owing last week's $15,000 still shows as overdue,
        and is not charged this week."""
        leaver = make_contractor("leaver", "1009", self.w.taylor)
        leaver.is_active = False
        leaver.deactivated_on = date(2026, 11, 8)
        leaver.save()
        self.client.force_login(self.w.owner)
        taylor = self.card(self.client.get(reverse("owner_home")), self.w.taylor)
        self.assertEqual(taylor["overdue"], Decimal("45000"))      # 30,000 as before + the leaver's 15,000
        self.assertEqual(taylor["outstanding"], Decimal("25000"))  # unchanged: nothing charged this week

    def test_company_supervisor_sees_how_many_handoffs_wait_for_them(self):
        Handoff.objects.create(
            step=HandoffStep.SHOP_TO_COMPANY, shop=self.w.taylor, rent_period=self.w.period,
            expected_amount=Decimal("0"), amount_handed=Decimal("100"), handed_date=TODAY - timedelta(days=1),
            handed_by=self.w.taylor_sup.user, status=HandoffStatus.AWAITING,
        )
        self.client.force_login(self.w.company)
        response = self.client.get(reverse("company_home"))
        self.assertEqual(response.context["waiting_count"], 1)
        self.assertContains(response, "waiting for you to confirm")
        self.assertTrue(self.card(response, self.w.taylor)["needs_action"])

    def test_owner_strip_counts_only_the_owner_handoff(self):
        Handoff.objects.create(
            step=HandoffStep.SHOP_TO_COMPANY, shop=self.w.taylor, rent_period=self.w.period,
            expected_amount=Decimal("0"), amount_handed=Decimal("100"), handed_date=TODAY - timedelta(days=1),
            handed_by=self.w.taylor_sup.user, status=HandoffStatus.AWAITING,
        )
        self.client.force_login(self.w.owner)
        response = self.client.get(reverse("owner_home"))
        self.assertEqual(response.context["waiting_count"], 0)
        self.assertNotContains(response, "waiting for you to confirm")
