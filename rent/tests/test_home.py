"""Home pages: supervisor contractor list order and the shops overview."""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from rent.models import Contractor, PayType, Payment, ShopAssignment
from rent.services import rent_rules
from rent.tests.helpers import PASSWORD, make_world
from rent.views.home import supervisor_rows


class SupervisorRowsTests(TestCase):
    def setUp(self):
        self.w = make_world()
        self.contractors = Contractor.objects.filter(shop=self.w.taylor)

    def pay(self, contractor, amount):
        Payment.objects.create(contractor=contractor, rent_period=self.w.period, amount=Decimal(amount),
                               payment_date=date(2026, 11, 3), recorded_by=self.w.taylor_sup.user)

    def names(self, rows):
        return [r["contractor"] for r in rows]

    def test_unpaid_listed_before_paid(self):
        self.pay(self.w.taylor_sup, 15000)
        rows = supervisor_rows(self.contractors, self.w.period, today=date(2026, 11, 5))
        self.assertEqual(self.names(rows), [self.w.taylor_c, self.w.taylor_sup])
        self.assertEqual(rows[1]["summary"]["status"], rent_rules.PAID)

    def test_partly_paid_after_unpaid_and_before_paid(self):
        self.pay(self.w.taylor_sup, 5000)
        rows = supervisor_rows(self.contractors, self.w.period, today=date(2026, 11, 5))
        self.assertEqual(self.names(rows), [self.w.taylor_c, self.w.taylor_sup])
        self.assertEqual(rows[1]["summary"]["status"], rent_rules.PARTLY_PAID)

    def test_overdue_listed_first_with_total(self):
        # Due Friday 6 Nov; on Monday 9 Nov the unpaid $10,000 is overdue.
        self.pay(self.w.taylor_c, 5000)
        rows = supervisor_rows(self.contractors, self.w.period, today=date(2026, 11, 9))
        self.assertEqual(rows[0]["overdue_total"], Decimal("15000"))  # taylor_sup paid nothing
        self.assertEqual(rows[1]["overdue_total"], Decimal("10000"))

    def test_nothing_overdue_before_due_day(self):
        rows = supervisor_rows(self.contractors, self.w.period, today=date(2026, 11, 6))
        self.assertTrue(all(r["overdue_total"] == 0 for r in rows))

    def test_pay_type_is_the_one_for_this_week(self):
        # Changed to commission from this week; the contractor record still says weekly rent (US-05 AC-3).
        ShopAssignment.objects.create(contractor=self.w.taylor_c, shop=self.w.taylor,
                                      pay_type=PayType.COMMISSION, effective_from=self.w.period.start_date)
        rows = supervisor_rows(self.contractors, self.w.period, today=date(2026, 11, 5))
        by_contractor = {r["contractor"]: r["pay_type"] for r in rows}
        self.assertEqual(by_contractor[self.w.taylor_c], PayType.COMMISSION.label)
        self.assertEqual(by_contractor[self.w.taylor_sup], PayType.WEEKLY_RENT.label)


class HomePageTests(TestCase):
    def setUp(self):
        self.w = make_world()

    def login(self, user):
        self.client.login(username=user.username, password=PASSWORD)

    def test_supervisor_home_shows_outstanding_and_record_links(self):
        self.login(self.w.taylor_sup.user)
        r = self.client.get(reverse("supervisor_home"))
        self.assertContains(r, "Still to collect")
        self.assertContains(r, f'href="{reverse("record_payment")}?contractor={self.w.taylor_c.pk}"')

    def test_owner_and_company_see_every_shop(self):
        for user, heading in [(self.w.owner, "Your shops"), (self.w.company, "All shops")]:
            self.login(user)
            r = self.client.get(reverse("home"), follow=True)
            self.assertContains(r, heading)
            self.assertContains(r, self.w.taylor.name)
            self.assertContains(r, self.w.utech.name)
            self.assertContains(r, reverse("dashboard"))
