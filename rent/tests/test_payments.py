"""Tests for US-01 Record rent payments (SRS US-01 AC-1 to AC-7).

SRS scenario data from make_world(): Taylor Hall $15,000 due Friday,
rent period 2 to 8 Nov 2026. Each test is named after the SRS scenario.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from rent.models import (CommissionEarning, PayType, Payment, PaymentCorrection,
                         RentPeriod)
from rent.services import payments, rent_rules

from .helpers import PASSWORD, make_world

PAID_ON = date(2026, 11, 6)  # the Friday due date in the SRS scenario


class PaymentServiceTestCase(TestCase):
    def setUp(self):
        self.w = make_world()
        self.c = self.w.taylor_c          # Kemar's place in the SRS scenario
        self.sup = self.w.taylor_sup.user

    def record(self, amount, **kw):
        args = dict(contractor=self.c, period=self.w.period, amount=amount,
                    payment_date=PAID_ON, recorded_by=self.sup)
        args.update(kw)
        return payments.record_payment(**args)

    def make_commission(self):
        self.c.pay_type = PayType.COMMISSION
        self.c.save()


class RecordPaymentTests(PaymentServiceTestCase):
    def test_ac1_ac4_full_payment_15000_is_paid(self):
        p = self.record("15000")
        p.refresh_from_db()
        self.assertEqual((p.contractor, p.amount, p.payment_date, p.rent_period, p.recorded_by),
                         (self.c, Decimal("15000.00"), PAID_ON, self.w.period, self.sup))
        self.assertEqual(rent_rules.status(self.c, self.w.period), "Paid")

    def test_ac2_ac4_part_payment_10000_is_partly_paid_5000_owed(self):
        self.record("10000")
        self.assertEqual(rent_rules.status(self.c, self.w.period), "Partly paid")
        self.assertEqual(rent_rules.balance(self.c, self.w.period), Decimal("5000"))

    def test_ac2_second_part_payment_clears_balance(self):
        self.record("10000")
        self.record("5000")
        self.assertEqual(rent_rules.status(self.c, self.w.period), "Paid")

    def test_ac2_over_balance_20000_rejected_says_15000_is_most(self):
        with self.assertRaises(ValidationError) as e:
            self.record("20000")
        self.assertIn("The most you can record is $15,000", e.exception.messages[0])
        self.assertEqual(Payment.objects.count(), 0)

    def test_ac2_over_remaining_balance_after_part_payment(self):
        self.record("10000")
        with self.assertRaises(ValidationError) as e:
            self.record("6000")
        self.assertIn("$5,000", e.exception.messages[0])

    def test_ac2_already_paid_in_full_rejects_more(self):
        self.record("15000")
        with self.assertRaises(ValidationError) as e:
            self.record("1")
        self.assertIn("already paid in full", e.exception.messages[0])

    def test_ac2_zero_negative_non_numeric_and_missing_amounts_rejected(self):
        for bad in ("0", "-500", "abc", "", None, "   ", "NaN", "12.345"):
            with self.subTest(amount=bad), self.assertRaises(ValidationError):
                self.record(bad)
        self.assertEqual(Payment.objects.count(), 0)

    def test_amount_stored_as_decimal(self):
        p = self.record("10000.50")
        self.assertIsInstance(p.amount, Decimal)
        self.assertEqual(p.amount, Decimal("10000.50"))

    def test_ac3_future_payment_date_rejected(self):
        tomorrow = timezone.localdate() + timedelta(days=1)
        with self.assertRaises(ValidationError) as e:
            self.record("15000", payment_date=tomorrow)
        self.assertIn("future", e.exception.messages[0])
        self.assertEqual(Payment.objects.count(), 0)

    def test_ac3_period_after_current_rejected(self):
        future = RentPeriod.for_date(timezone.localdate() + timedelta(days=7))
        with self.assertRaises(ValidationError) as e:
            self.record("15000", period=future)
        self.assertIn("future rent period", e.exception.messages[0])

    def test_ac3_every_field_required(self):
        for missing in ("period", "payment_date", "contractor"):
            with self.subTest(missing=missing), self.assertRaises(ValidationError):
                self.record("15000", **{missing: None})
        with self.assertRaises(ValidationError):
            self.record("15000", payment_date="")
        self.assertEqual(Payment.objects.count(), 0)

    def test_ac5_supervisor_cannot_record_for_another_shop(self):
        with self.assertRaises(PermissionDenied):
            self.record("12000", contractor=self.w.utech_c)
        self.assertEqual(Payment.objects.count(), 0)

    def test_ac5_only_shop_supervisor_can_record(self):
        for user in (self.w.owner, self.w.company, self.c.user):
            with self.subTest(user=user.username), self.assertRaises(PermissionDenied):
                self.record("15000", recorded_by=user)

    def test_deactivated_contractor_can_still_pay_balance(self):  # US-05 AC-6
        self.c.is_active = False
        self.c.save()
        self.record("15000")
        self.assertEqual(rent_rules.status(self.c, self.w.period), "Paid")

    def test_commission_payment_needs_earnings_first(self):
        self.make_commission()
        with self.assertRaises(ValidationError) as e:
            self.record("1000")
        self.assertIn("earnings", e.exception.messages[0])

    def test_payment_cannot_be_deleted(self):  # SF-1
        p = self.record("15000")
        with self.assertRaises(PermissionDenied):
            p.delete()
        with self.assertRaises(PermissionDenied):
            Payment.objects.filter(pk=p.pk).delete()
        self.assertTrue(Payment.objects.filter(pk=p.pk).exists())


class CommissionEarningsTests(PaymentServiceTestCase):
    def enter(self, earnings, **kw):
        args = dict(contractor=self.c, period=self.w.period, earnings=earnings, entered_by=self.sup)
        args.update(kw)
        return payments.enter_commission_earnings(**args)

    def test_ac6_commission_30000_earnings_gives_12000_owed(self):
        self.make_commission()
        self.enter("30000")
        self.assertEqual(rent_rules.amount_owed(self.c, self.w.period), Decimal("12000.00"))
        self.record("12000")
        self.assertEqual(rent_rules.status(self.c, self.w.period), "Paid")

    def test_ac6_updating_earnings_keeps_one_row(self):
        self.make_commission()
        self.enter("30000")
        self.enter("25000")
        self.assertEqual(CommissionEarning.objects.filter(contractor=self.c).count(), 1)
        self.assertEqual(rent_rules.amount_owed(self.c, self.w.period), Decimal("10000.00"))

    def test_ac6_zero_earnings_allowed_negative_rejected(self):
        self.make_commission()
        self.enter("0")
        self.assertEqual(rent_rules.status(self.c, self.w.period), "Paid")
        with self.assertRaises(ValidationError):
            self.enter("-1")

    def test_ac6_earnings_cannot_drop_below_what_is_paid(self):
        self.make_commission()
        self.enter("30000")
        self.record("12000")
        with self.assertRaises(ValidationError):
            self.enter("20000")  # 40% = 8,000 < 12,000 paid

    def test_ac6_rent_contractor_has_no_earnings(self):
        with self.assertRaises(ValidationError):
            self.enter("30000")

    def test_ac5_earnings_only_at_own_shop(self):
        self.w.utech_c.pay_type = PayType.COMMISSION
        self.w.utech_c.save()
        with self.assertRaises(PermissionDenied):
            self.enter("30000", contractor=self.w.utech_c)


class CorrectPaymentTests(PaymentServiceTestCase):
    def correct(self, payment, amount, reason="Typing error", **kw):
        args = dict(payment=payment, new_amount=amount, new_payment_date=PAID_ON,
                    reason=reason, corrected_by=self.sup)
        args.update(kw)
        return payments.correct_payment(**args)

    def test_ac7_correct_15000_to_12000_typing_error_keeps_original(self):
        p = self.record("15000")
        self.correct(p, "12000")
        p.refresh_from_db()
        self.assertEqual(p.amount, Decimal("12000"))
        fix = PaymentCorrection.objects.get(payment=p)
        self.assertEqual((fix.old_amount, fix.new_amount, fix.reason, fix.corrected_by),
                         (Decimal("15000"), Decimal("12000"), "Typing error", self.sup))
        self.assertEqual((fix.old_payment_date, fix.new_payment_date), (PAID_ON, PAID_ON))
        self.assertIsNotNone(fix.corrected_at)
        self.assertEqual(rent_rules.status(self.c, self.w.period), "Partly paid")
        self.assertEqual(Payment.objects.count(), 1)  # nothing deleted or added

    def test_ac7_correction_with_no_reason_rejected(self):
        p = self.record("15000")
        for blank in ("", "   ", None):
            with self.subTest(reason=blank), self.assertRaises(ValidationError) as e:
                self.correct(p, "12000", reason=blank)
            self.assertIn("reason", e.exception.messages[0])
        p.refresh_from_db()
        self.assertEqual(p.amount, Decimal("15000"))
        self.assertFalse(PaymentCorrection.objects.exists())

    def test_ac7_correction_cannot_push_total_over_owed(self):
        first = self.record("10000")
        self.record("5000")
        with self.assertRaises(ValidationError) as e:
            self.correct(first, "11000")
        self.assertIn("The most you can record is $10,000", e.exception.messages[0])

    def test_ac7_correction_can_change_date(self):
        p = self.record("15000")
        self.correct(p, "15000", new_payment_date=date(2026, 11, 5))
        p.refresh_from_db()
        self.assertEqual(p.payment_date, date(2026, 11, 5))

    def test_ac7_correction_future_date_and_bad_amount_rejected(self):
        p = self.record("15000")
        with self.assertRaises(ValidationError):
            self.correct(p, "15000", new_payment_date=timezone.localdate() + timedelta(days=1))
        for bad in ("0", "-1", "abc", ""):
            with self.subTest(amount=bad), self.assertRaises(ValidationError):
                self.correct(p, bad)

    def test_ac5_ac7_only_own_shop_supervisor_can_correct(self):
        p = self.record("15000")
        for user in (self.w.utech_sup.user, self.w.owner, self.c.user):
            with self.subTest(user=user.username), self.assertRaises(PermissionDenied):
                self.correct(p, "12000", corrected_by=user)

    def test_two_corrections_keep_full_history(self):
        p = self.record("15000")
        self.correct(p, "12000")
        self.correct(p, "13000", reason="Counted again")
        self.assertEqual(
            list(PaymentCorrection.objects.filter(payment=p).order_by("corrected_at")
                 .values_list("old_amount", "new_amount")),
            [(Decimal("15000"), Decimal("12000")), (Decimal("12000"), Decimal("13000"))],
        )


class PaymentPageTests(TestCase):
    def setUp(self):
        self.w = make_world()
        self.c = self.w.taylor_c
        self.client.login(username=self.w.taylor_sup.user.username, password=PASSWORD)
        self.url = reverse("record_payment")

    def post_payment(self, amount, payment_date="2026-11-06", contractor=None):
        return self.client.post(self.url, {
            "action": "payment", "contractor": (contractor or self.c).pk,
            "period": self.w.period.pk, "amount": amount, "payment_date": payment_date,
        }, follow=True)

    def test_ac4_full_payment_page_shows_paid(self):
        r = self.post_payment("15000")
        self.assertContains(r, "Status: Paid.")
        self.assertEqual(Payment.objects.count(), 1)

    def test_ac4_part_payment_page_shows_partly_paid_and_5000_owed(self):
        r = self.post_payment("10000")
        self.assertContains(r, "Status: Partly paid. $5,000 still owed.")

    def test_ac2_over_balance_page_shows_message_and_saves_nothing(self):
        r = self.post_payment("20000")
        self.assertContains(r, "The most you can record is $15,000")
        self.assertEqual(Payment.objects.count(), 0)

    def test_ac3_future_date_page_shows_message(self):
        tomorrow = (timezone.localdate() + timedelta(days=1)).isoformat()
        r = self.post_payment("15000", payment_date=tomorrow)
        self.assertContains(r, "cannot be in the future")
        self.assertEqual(Payment.objects.count(), 0)

    def test_page_shows_owed_paid_balance(self):
        r = self.client.get(self.url, {"contractor": self.c.pk, "period": self.w.period.pk})
        self.assertContains(r, "$15,000")
        self.assertContains(r, "Unpaid")

    def test_ac5_list_shows_only_own_shop(self):
        r = self.client.get(self.url)
        self.assertContains(r, self.c.full_name)
        self.assertNotContains(r, self.w.utech_c.full_name)

    def test_ac5_typed_url_for_other_shop_is_403(self):
        r = self.client.get(self.url, {"contractor": self.w.utech_c.pk})
        self.assertEqual(r.status_code, 403)
        r = self.post_payment("12000", contractor=self.w.utech_c)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(Payment.objects.count(), 0)

    def test_ac5_other_roles_cannot_open_page(self):
        for user in (self.w.owner, self.w.company, self.c.user):
            self.client.login(username=user.username, password=PASSWORD)
            self.assertEqual(self.client.get(self.url).status_code, 403, user)

    def test_ac6_commission_page_asks_for_earnings(self):
        self.c.pay_type = PayType.COMMISSION
        self.c.save()
        r = self.client.get(self.url, {"contractor": self.c.pk, "period": self.w.period.pk})
        self.assertContains(r, "Commission earnings")
        self.assertNotContains(r, "Save payment")
        r = self.client.post(self.url, {"action": "earnings", "contractor": self.c.pk,
                                        "period": self.w.period.pk, "earnings": "30000"}, follow=True)
        self.assertContains(r, "owes $12,000")
        self.assertContains(r, "Save payment")

    def test_ac7_correct_page_saves_and_shows_history(self):
        p = Payment.objects.create(contractor=self.c, rent_period=self.w.period, amount=Decimal("15000"),
                                   payment_date=PAID_ON, recorded_by=self.w.taylor_sup.user)
        url = reverse("correct_payment", args=[p.pk])
        r = self.client.post(url, {"amount": "12000", "payment_date": "2026-11-06", "reason": ""})
        self.assertContains(r, "Enter a reason")
        r = self.client.post(url, {"amount": "12000", "payment_date": "2026-11-06",
                                   "reason": "Typing error"}, follow=True)
        self.assertContains(r, "corrected from $15,000 to $12,000")
        r = self.client.get(url)
        self.assertContains(r, "Typing error")
        self.assertContains(r, "$15,000 → $12,000")

    def test_ac5_correct_other_shops_payment_is_403(self):
        p = Payment.objects.create(contractor=self.w.utech_c, rent_period=self.w.period,
                                   amount=Decimal("12000"), payment_date=PAID_ON,
                                   recorded_by=self.w.utech_sup.user)
        url = reverse("correct_payment", args=[p.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, {"amount": "1", "payment_date": "2026-11-06",
                                                "reason": "x"}).status_code, 403)

    def test_qa1_record_payment_reachable_from_home(self):
        r = self.client.get(reverse("supervisor_home"))
        self.assertContains(r, f'href="{self.url}"')
        self.assertContains(r, f'href="{self.url}?contractor={self.c.pk}"')
