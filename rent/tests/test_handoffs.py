
"""Tests for US-03: Record and confirm rent handoffs."""

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone

from rent.models import (
    Handoff,
    HandoffStatus,
    HandoffStep,
    Payment,
)

from rent.services.handoffs import (
    confirm_handoff,
    record_owner_handoff,
    record_shop_handoff,
)

from .helpers import make_world


class HandoffTests(TestCase):

    def setUp(self):
        self.w = make_world()

    def create_shop_payments(self):
        """Create payments totalling $45,000 at Taylor Hall."""

        for amount, staff in (
            (15000, self.w.taylor_sup),
            (15000, self.w.taylor_c),
            (15000, self.w.taylor_c),
        ):
            Payment.objects.create(
                contractor=staff,
                rent_period=self.w.period,
                amount=Decimal(amount),
                payment_date=self.w.period.end_date,
                recorded_by=self.w.taylor_sup.user,
            )

    def test_shop_handoff_uses_expected_payment_total(self):
        self.create_shop_payments()

        handoff = record_shop_handoff(
            shop=self.w.taylor,
            period=self.w.period,
            amount=Decimal("45000"),
            handed_date=self.w.period.end_date,
            handed_by=self.w.taylor_sup.user,
        )

        self.assertEqual(handoff.expected_amount, Decimal("45000"))
        self.assertEqual(handoff.amount_handed, Decimal("45000"))
        self.assertEqual(handoff.status, HandoffStatus.AWAITING)
        self.assertFalse(handoff.is_mismatch)

    def test_shop_handoff_detects_mismatch(self):
        self.create_shop_payments()

        handoff = record_shop_handoff(
            shop=self.w.taylor,
            period=self.w.period,
            amount=Decimal("40000"),
            handed_date=self.w.period.end_date,
            handed_by=self.w.taylor_sup.user,
        )

        self.assertEqual(handoff.expected_amount, Decimal("45000"))
        self.assertTrue(handoff.is_mismatch)

    def test_duplicate_shop_handoff_is_rejected(self):
        details = {
            "shop": self.w.taylor,
            "period": self.w.period,
            "amount": Decimal("45000"),
            "handed_date": self.w.period.end_date,
            "handed_by": self.w.taylor_sup.user,
        }

        record_shop_handoff(**details)

        with self.assertRaises(ValidationError):
            record_shop_handoff(**details)

        self.assertEqual(
            Handoff.objects.filter(
                shop=self.w.taylor,
                rent_period=self.w.period,
                step=HandoffStep.SHOP_TO_COMPANY,
            ).count(),
            1,
        )

    def test_zero_handoff_amount_is_rejected(self):
        with self.assertRaises(ValidationError):
            record_shop_handoff(
                shop=self.w.taylor,
                period=self.w.period,
                amount=Decimal("0"),
                handed_date=self.w.period.end_date,
                handed_by=self.w.taylor_sup.user,
            )

    def test_negative_handoff_amount_is_rejected(self):
        with self.assertRaises(ValidationError):
            record_shop_handoff(
                shop=self.w.taylor,
                period=self.w.period,
                amount=Decimal("-100"),
                handed_date=self.w.period.end_date,
                handed_by=self.w.taylor_sup.user,
            )

    def test_amount_with_more_than_two_decimal_places_is_rejected(self):
        with self.assertRaises(ValidationError):
            record_shop_handoff(
                shop=self.w.taylor,
                period=self.w.period,
                amount=Decimal("100.123"),
                handed_date=self.w.period.end_date,
                handed_by=self.w.taylor_sup.user,
            )

    def test_future_handoff_date_is_rejected(self):
        tomorrow = timezone.localdate() + timedelta(days=1)

        with self.assertRaises(ValidationError):
            record_shop_handoff(
                shop=self.w.taylor,
                period=self.w.period,
                amount=Decimal("45000"),
                handed_date=tomorrow,
                handed_by=self.w.taylor_sup.user,
            )

    def test_supervisor_cannot_record_for_another_shop(self):
        with self.assertRaises(PermissionDenied):
            record_shop_handoff(
                shop=self.w.utech,
                period=self.w.period,
                amount=Decimal("12000"),
                handed_date=self.w.period.end_date,
                handed_by=self.w.taylor_sup.user,
            )

    def test_non_shop_supervisor_cannot_record_shop_handoff(self):
        with self.assertRaises(PermissionDenied):
            record_shop_handoff(
                shop=self.w.taylor,
                period=self.w.period,
                amount=Decimal("45000"),
                handed_date=self.w.period.end_date,
                handed_by=self.w.company,
            )

    def test_company_supervisor_confirms_shop_handoff(self):
        handoff = record_shop_handoff(
            shop=self.w.taylor,
            period=self.w.period,
            amount=Decimal("45000"),
            handed_date=self.w.period.end_date,
            handed_by=self.w.taylor_sup.user,
        )

        confirmed = confirm_handoff(
            handoff=handoff,
            amount_received=Decimal("45000"),
            confirmed_by=self.w.company,
        )

        self.assertEqual(confirmed.status, HandoffStatus.CONFIRMED)
        self.assertEqual(confirmed.amount_received, Decimal("45000"))
        self.assertEqual(confirmed.confirmed_by, self.w.company)
        self.assertIsNotNone(confirmed.confirmed_at)

    def test_wrong_role_cannot_confirm_shop_handoff(self):
        handoff = record_shop_handoff(
            shop=self.w.taylor,
            period=self.w.period,
            amount=Decimal("45000"),
            handed_date=self.w.period.end_date,
            handed_by=self.w.taylor_sup.user,
        )

        with self.assertRaises(PermissionDenied):
            confirm_handoff(
                handoff=handoff,
                amount_received=Decimal("45000"),
                confirmed_by=self.w.owner,
            )

    def test_owner_handoff_expected_amount_uses_confirmed_shop_receipts(self):
        for shop, supervisor, amount in (
            (self.w.taylor, self.w.taylor_sup, Decimal("45000")),
            (self.w.utech, self.w.utech_sup, Decimal("36000")),
        ):
            handoff = record_shop_handoff(
                shop=shop,
                period=self.w.period,
                amount=amount,
                handed_date=self.w.period.end_date,
                handed_by=supervisor.user,
            )

            confirm_handoff(
                handoff=handoff,
                amount_received=amount,
                confirmed_by=self.w.company,
            )

        owner_handoff = record_owner_handoff(
            period=self.w.period,
            amount=Decimal("81000"),
            handed_date=self.w.period.end_date,
            handed_by=self.w.company,
        )

        self.assertEqual(
            owner_handoff.expected_amount,
            Decimal("81000"),
        )
        self.assertFalse(owner_handoff.is_mismatch)

    def test_unconfirmed_shop_handoffs_are_excluded_from_owner_expected_amount(self):
        confirmed_handoff = record_shop_handoff(
            shop=self.w.taylor,
            period=self.w.period,
            amount=Decimal("45000"),
            handed_date=self.w.period.end_date,
            handed_by=self.w.taylor_sup.user,
        )

        confirm_handoff(
            handoff=confirmed_handoff,
            amount_received=Decimal("45000"),
            confirmed_by=self.w.company,
        )

        record_shop_handoff(
            shop=self.w.utech,
            period=self.w.period,
            amount=Decimal("36000"),
            handed_date=self.w.period.end_date,
            handed_by=self.w.utech_sup.user,
        )

        owner_handoff = record_owner_handoff(
            period=self.w.period,
            amount=Decimal("45000"),
            handed_date=self.w.period.end_date,
            handed_by=self.w.company,
        )

        self.assertEqual(
            owner_handoff.expected_amount,
            Decimal("45000"),
        )

    def test_owner_confirms_owner_handoff(self):
        owner_handoff = record_owner_handoff(
            period=self.w.period,
            amount=Decimal("81000"),
            handed_date=self.w.period.end_date,
            handed_by=self.w.company,
        )

        confirmed = confirm_handoff(
            handoff=owner_handoff,
            amount_received=Decimal("80000"),
            confirmed_by=self.w.owner,
        )

        self.assertEqual(confirmed.status, HandoffStatus.CONFIRMED)
        self.assertEqual(confirmed.amount_received, Decimal("80000"))
        self.assertEqual(confirmed.confirmed_by, self.w.owner)
        self.assertIsNotNone(confirmed.confirmed_at)
        self.assertTrue(confirmed.is_mismatch)

    def test_wrong_role_cannot_confirm_owner_handoff(self):
        owner_handoff = record_owner_handoff(
            period=self.w.period,
            amount=Decimal("81000"),
            handed_date=self.w.period.end_date,
            handed_by=self.w.company,
        )

        with self.assertRaises(PermissionDenied):
            confirm_handoff(
                handoff=owner_handoff,
                amount_received=Decimal("81000"),
                confirmed_by=self.w.company,
            )

    def test_duplicate_owner_handoff_is_rejected(self):
        details = {
            "period": self.w.period,
            "amount": Decimal("81000"),
            "handed_date": self.w.period.end_date,
            "handed_by": self.w.company,
        }

        record_owner_handoff(**details)

        with self.assertRaises(ValidationError):
            record_owner_handoff(**details)

    def test_non_company_supervisor_cannot_record_owner_handoff(self):
        with self.assertRaises(PermissionDenied):
            record_owner_handoff(
                period=self.w.period,
                amount=Decimal("81000"),
                handed_date=self.w.period.end_date,
                handed_by=self.w.owner,
            )

    def test_handoff_cannot_be_confirmed_twice(self):
        handoff = record_shop_handoff(
            shop=self.w.taylor,
            period=self.w.period,
            amount=Decimal("45000"),
            handed_date=self.w.period.end_date,
            handed_by=self.w.taylor_sup.user,
        )

        confirm_handoff(
            handoff=handoff,
            amount_received=Decimal("45000"),
            confirmed_by=self.w.company,
        )

        with self.assertRaises(ValidationError):
            confirm_handoff(
                handoff=handoff,
                amount_received=Decimal("45000"),
                confirmed_by=self.w.company,
            )
