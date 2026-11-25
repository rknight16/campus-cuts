"""US-06 tests: View my rent, due date and payment history. One test per SRS scenario, plus UC-06 alternate flows.

SRS data from make_world(): Taylor Hall $15,000 due Friday, rent period 2 to 8 Nov 2026 (due Friday 6 Nov).
"""
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from rent.models import CommissionEarning, PayType, Payment, RentPeriod
from rent.services import rent_rules

from .helpers import make_world


class AccountTestCase(TestCase):
    today = date(2026, 11, 4)  # Wednesday of 2 to 8 Nov 2026

    def setUp(self):
        patcher = patch("django.utils.timezone.localdate", return_value=self.today)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.w = make_world()
        self.me = self.w.taylor_c
        self.client.force_login(self.me.user)

    def pay(self, amount, on=date(2026, 11, 3), period=None):
        return Payment.objects.create(
            contractor=self.me, rent_period=period or self.w.period, amount=Decimal(amount),
            payment_date=on, recorded_by=self.w.taylor_sup.user,
        )

    def open_page(self):
        return self.client.get(reverse("my_account"))


class ThisWeekTests(AccountTestCase):
    def test_ac1_contractor_checks_this_weeks_rent(self):
        """Paid $10,000 of $15,000; opens the page Wed 4 Nov: owed, paid, balance, due Fri 6 Nov, Partly paid."""
        self.pay(10000)
        response = self.open_page()
        rent = response.context["rent"]
        self.assertEqual(rent["owed"], Decimal("15000"))
        self.assertEqual(rent["paid"], Decimal("10000"))
        self.assertEqual(rent["balance"], Decimal("5000"))
        self.assertEqual(rent["due_date"], date(2026, 11, 6))
        self.assertEqual(rent["status"], rent_rules.PARTLY_PAID)
        self.assertContains(response, "Friday 6 Nov")
        self.assertContains(response, "Partly paid")
        self.assertNotContains(response, "US-06 (Raynardo)")  # the placeholder is gone

    def test_ac1_nothing_paid_is_unpaid(self):
        rent = self.open_page().context["rent"]
        self.assertEqual(rent["status"], rent_rules.UNPAID)
        self.assertEqual(rent["balance"], Decimal("15000"))

    def test_a3_commission_shows_owed_only_once_earnings_are_entered(self):
        self.me.pay_type = PayType.COMMISSION
        self.me.save()
        response = self.open_page()
        self.assertIsNone(response.context["rent"]["owed"])
        self.assertContains(response, "has not entered this week")
        CommissionEarning.objects.create(contractor=self.me, rent_period=self.w.period,
                                         earnings=Decimal("30000"), entered_by=self.w.taylor_sup.user)
        self.assertEqual(self.open_page().context["rent"]["owed"], Decimal("12000"))


class OverdueAfterDueDayTests(AccountTestCase):
    today = date(2026, 11, 7)  # Saturday, the day after the due day

    def test_ac2_contractor_has_an_overdue_balance(self):
        """Paid only $10,000 of $15,000, due Fri 6 Nov; on Sat 7 Nov the page shows $5,000 overdue for 2 to 8 Nov."""
        self.pay(10000)
        response = self.open_page()
        rent = response.context["rent"]
        self.assertEqual(rent["overdue_total"], Decimal("5000"))
        self.assertEqual([(row["period"], row["balance"]) for row in rent["overdue"]],
                         [(self.w.period, Decimal("5000"))])
        self.assertContains(response, "Total overdue")
        self.assertContains(response, "2 Nov to 8 Nov 2026")

    def test_ac2_contractor_has_nothing_overdue(self):
        """Paid every rent period in full: the page shows $0 overdue (UC-06 A1)."""
        self.pay(15000)
        response = self.open_page()
        self.assertEqual(response.context["rent"]["overdue_total"], Decimal("0"))
        self.assertContains(response, "$0 overdue.")

    def test_no_overdue_for_weeks_before_joining(self):
        self.me.joined_on = date(2026, 11, 9)  # joins the week after
        self.me.save()
        self.assertEqual(self.open_page().context["rent"]["overdue_total"], Decimal("0"))


class HistoryTests(AccountTestCase):
    def test_ac3_contractor_views_their_payment_history(self):
        """Three payments, listed newest first with rent period, amount and payment date."""
        earlier = RentPeriod.for_date(date(2026, 10, 26))
        self.pay(3000, on=date(2026, 10, 27), period=earlier)
        self.pay(4000, on=date(2026, 11, 3))
        self.pay(5000, on=date(2026, 11, 4))
        response = self.open_page()
        amounts = [p.amount for p in response.context["payments"]]
        self.assertEqual(amounts, [Decimal("5000"), Decimal("4000"), Decimal("3000")])
        self.assertContains(response, "4 Nov 2026")
        self.assertContains(response, "26 Oct to 1 Nov 2026")

    def test_a2_no_payments_yet_says_so(self):
        self.assertContains(self.open_page(), "No payments have been recorded for you yet.")

    def test_receipt_column_waits_for_us07(self):
        self.pay(15000)
        self.assertNotContains(self.open_page(), "<th>Receipt</th>")


class AccessTests(AccountTestCase):
    def test_ac4_contractor_tries_to_view_someone_elses_page(self):
        """Typing another contractor's web address is denied."""
        other = reverse("contractor_account", args=[self.w.utech_c.pk])
        self.assertEqual(self.client.get(other).status_code, 403)

    def test_own_page_by_address_opens(self):
        own = reverse("contractor_account", args=[self.me.pk])
        self.assertEqual(self.client.get(own).status_code, 200)

    def test_shop_supervisor_sees_their_own_rent(self):
        self.client.force_login(self.w.taylor_sup.user)
        response = self.open_page()
        self.assertEqual(response.context["contractor"], self.w.taylor_sup)

    def test_plain_contractor_gets_no_one_tab_bar(self):
        self.assertNotContains(self.open_page(), '<nav class="tabs"')
