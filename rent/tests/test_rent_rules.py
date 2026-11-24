"""Tests for RentRules (US-01 AC-4, AC-6; used by US-04, US-06, US-07).

SRS scenario data from make_world(): Taylor Hall $15,000 due Friday,
rent period 2 to 8 Nov 2026 (due Friday 6 Nov).
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from rent.models import CommissionEarning, PayType, Payment, RentPeriod, RentSetting, Weekday
from rent.services import rent_rules

from .helpers import make_world


def pay(w, amount, contractor=None, period=None, on=date(2026, 11, 6)):
    return Payment.objects.create(
        contractor=contractor or w.taylor_c, rent_period=period or w.period,
        amount=Decimal(amount), payment_date=on, recorded_by=w.taylor_sup.user,
    )


class AmountOwedTests(TestCase):
    def setUp(self):
        self.w = make_world()

    def test_weekly_rent_is_shop_rent(self):
        self.assertEqual(rent_rules.amount_owed(self.w.taylor_c, self.w.period), Decimal("15000"))
        self.assertEqual(rent_rules.amount_owed(self.w.utech_c, self.w.period), Decimal("12000"))

    def test_rent_change_does_not_alter_earlier_period(self):  # US-02 AC-4, QA-2
        nxt = self.w.period.next()
        RentSetting.objects.create(shop=self.w.taylor, weekly_rent=Decimal("16000"),
                                   due_day=Weekday.FRIDAY, effective_from=nxt)
        self.assertEqual(rent_rules.amount_owed(self.w.taylor_c, self.w.period), Decimal("15000"))
        self.assertEqual(rent_rules.amount_owed(self.w.taylor_c, nxt), Decimal("16000"))

    def test_commission_30000_earnings_owes_12000(self):  # US-01 AC-6 scenario
        c = self.w.taylor_c
        c.pay_type = PayType.COMMISSION
        c.save()
        CommissionEarning.objects.create(contractor=c, rent_period=self.w.period,
                                         earnings=Decimal("30000"), entered_by=self.w.taylor_sup.user)
        owed = rent_rules.amount_owed(c, self.w.period)
        self.assertEqual(owed, Decimal("12000.00"))
        self.assertIsInstance(owed, Decimal)

    def test_commission_rounds_to_cents(self):
        c = self.w.taylor_c
        c.pay_type = PayType.COMMISSION
        c.save()
        CommissionEarning.objects.create(contractor=c, rent_period=self.w.period,
                                         earnings=Decimal("1000.05"), entered_by=self.w.taylor_sup.user)
        self.assertEqual(rent_rules.amount_owed(c, self.w.period), Decimal("400.02"))

    def test_commission_without_earnings_is_none(self):  # US-01 AC-6: shown once entered
        c = self.w.taylor_c
        c.pay_type = PayType.COMMISSION
        c.save()
        self.assertIsNone(rent_rules.amount_owed(c, self.w.period))
        self.assertIsNone(rent_rules.balance(c, self.w.period))
        self.assertEqual(rent_rules.status(c, self.w.period), rent_rules.AWAITING_EARNINGS)
        self.assertEqual(rent_rules.overdue_periods(c, today=date(2026, 11, 20)), [])


class StatusTests(TestCase):
    def setUp(self):
        self.w = make_world()

    def test_no_payments_is_unpaid_and_balance_equals_owed(self):
        c, p = self.w.taylor_c, self.w.period
        self.assertEqual(rent_rules.amount_paid(c, p), Decimal("0"))
        self.assertEqual(rent_rules.balance(c, p), Decimal("15000"))
        self.assertEqual(rent_rules.status(c, p), "Unpaid")

    def test_full_payment_is_paid(self):  # US-01 AC-4
        pay(self.w, 15000)
        self.assertEqual(rent_rules.status(self.w.taylor_c, self.w.period), "Paid")
        self.assertEqual(rent_rules.balance(self.w.taylor_c, self.w.period), Decimal("0"))

    def test_part_payment_is_partly_paid(self):  # US-01 AC-4
        pay(self.w, 10000)
        self.assertEqual(rent_rules.status(self.w.taylor_c, self.w.period), "Partly paid")
        self.assertEqual(rent_rules.balance(self.w.taylor_c, self.w.period), Decimal("5000"))

    def test_two_part_payments_add_up(self):
        pay(self.w, 10000)
        pay(self.w, 5000)
        self.assertEqual(rent_rules.amount_paid(self.w.taylor_c, self.w.period), Decimal("15000"))
        self.assertEqual(rent_rules.status(self.w.taylor_c, self.w.period), "Paid")

    def test_balance_never_below_zero(self):
        pay(self.w, 16000)  # only possible by writing straight to the table
        self.assertEqual(rent_rules.balance(self.w.taylor_c, self.w.period), Decimal("0"))

    def test_other_contractors_payments_not_counted(self):
        pay(self.w, 15000, contractor=self.w.utech_c)
        self.assertEqual(rent_rules.status(self.w.taylor_c, self.w.period), "Unpaid")

    def test_summary(self):
        pay(self.w, 10000)
        s = rent_rules.summary(self.w.taylor_c, self.w.period)
        self.assertEqual(s, {"owed": Decimal("15000"), "paid": Decimal("10000"),
                             "balance": Decimal("5000"), "status": "Partly paid"})


class OverdueTests(TestCase):
    """Due Friday 6 Nov 2026. Overdue from Saturday 7 Nov if a balance is left."""
    def setUp(self):
        self.w = make_world()

    def test_not_overdue_before_due_day(self):
        self.assertEqual(rent_rules.overdue_periods(self.w.taylor_c, today=date(2026, 11, 5)), [])

    def test_not_overdue_on_due_day(self):
        self.assertEqual(rent_rules.overdue_periods(self.w.taylor_c, today=date(2026, 11, 6)), [])

    def test_overdue_after_due_day(self):
        self.assertEqual(rent_rules.overdue_periods(self.w.taylor_c, today=date(2026, 11, 7)),
                         [(self.w.period, Decimal("15000"))])

    def test_part_payment_overdue_for_the_rest(self):
        pay(self.w, 10000)
        self.assertEqual(rent_rules.overdue_periods(self.w.taylor_c, today=date(2026, 11, 7)),
                         [(self.w.period, Decimal("5000"))])

    def test_paid_in_full_is_not_overdue(self):
        pay(self.w, 15000)
        # 13 Nov is the next week's due day, so that week is not overdue yet either
        self.assertEqual(rent_rules.overdue_periods(self.w.taylor_c, today=date(2026, 11, 13)), [])

    def test_several_periods_oldest_first(self):
        nxt = self.w.period.next()  # 9 to 15 Nov, due 13 Nov
        result = rent_rules.overdue_periods(self.w.taylor_c, today=date(2026, 11, 14))
        self.assertEqual(result, [(self.w.period, Decimal("15000")), (nxt, Decimal("15000"))])

    def test_default_today_is_local_date(self):
        # Without `today` it uses timezone.localdate(); passing that in gives the same answer.
        from django.utils import timezone

        def weeks(result):  # unsaved weeks are new objects each call, so compare by date and amount
            return [(p.start_date, owing) for p, owing in result]
        self.assertEqual(weeks(rent_rules.overdue_periods(self.w.taylor_c)),
                         weeks(rent_rules.overdue_periods(self.w.taylor_c, today=timezone.localdate())))

    def test_week_nobody_opened_still_counts(self):
        """No RentPeriod row exists for 9 to 15 Nov, but its unpaid rent is still overdue on 14 Nov."""
        pay(self.w, 15000)
        result = rent_rules.overdue_periods(self.w.taylor_c, today=date(2026, 11, 14))
        self.assertEqual([(p.start_date, owing) for p, owing in result], [(date(2026, 11, 9), Decimal("15000"))])
        self.assertFalse(RentPeriod.objects.filter(start_date=date(2026, 11, 9)).exists())  # nothing saved

    def test_no_overdue_before_the_contractor_joined(self):
        """Joined Wednesday 11 Nov: the 2 to 8 Nov week is not theirs, only 9 to 15 Nov is."""
        self.w.taylor_c.joined_on = date(2026, 11, 11)
        self.w.taylor_c.save()
        result = rent_rules.overdue_periods(self.w.taylor_c, today=date(2026, 11, 14))
        self.assertEqual([p.start_date for p, _ in result], [date(2026, 11, 9)])

    def test_commission_week_without_earnings_is_not_overdue(self):
        self.w.taylor_c.pay_type = PayType.COMMISSION
        self.w.taylor_c.save()
        self.assertEqual(rent_rules.overdue_periods(self.w.taylor_c, today=date(2026, 11, 14)), [])


class SeedOverdueTests(TestCase):
    """After `seed`, only last week's three short payers are overdue (dashboard/US-06 demo)."""
    def test_seed_overdue_is_only_last_weeks_short_payers(self):
        from io import StringIO

        from django.core.management import call_command

        from rent.models import Contractor
        call_command("seed", stdout=StringIO())
        overdue = {c.staff_id: [b for _, b in rent_rules.overdue_periods(c)]
                   for c in Contractor.objects.all() if rent_rules.overdue_periods(c)}
        self.assertEqual(overdue, {"1003": [Decimal("5000")], "1010": [Decimal("18000")],
                                   "1014": [Decimal("6000")]})
