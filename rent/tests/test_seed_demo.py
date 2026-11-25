"""The demo data covers every feature, so nothing in the demo is empty (seed command)."""
import os
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from rent.models import (CommissionEarning, Contractor, Handoff, HandoffStatus, HandoffStep, Payment,
                         PaymentCorrection, Receipt, RentPeriod)
from rent.services import receipts, rent_settings
from rent.services.contractors import pay_type_for, shop_for


def seed(**env):
    with patch.dict(os.environ, env):
        if "DEMO_PHONE" not in env:
            os.environ.pop("DEMO_PHONE", None)
        call_command("seed", stdout=StringIO())


class SeedDemoDataTests(TestCase):
    def test_every_payment_has_a_receipt_and_one_is_corrected(self):
        seed()
        self.assertEqual(Receipt.objects.filter(corrects__isnull=True).count(), Payment.objects.count())
        self.assertEqual(PaymentCorrection.objects.count(), 1)
        self.assertEqual(Receipt.objects.filter(corrects__isnull=False).count(), 1)

    def test_kemar_has_a_payment_history(self):
        seed()
        self.assertEqual(Contractor.objects.get(staff_id="1002").payments.count(), 4)

    def test_handoffs_show_every_state(self):
        seed()
        shop = Handoff.objects.filter(step=HandoffStep.SHOP_TO_COMPANY)
        self.assertTrue(shop.filter(status=HandoffStatus.AWAITING).exists())
        self.assertTrue(shop.filter(status=HandoffStatus.CONFIRMED).exists())
        self.assertTrue(any(h.is_mismatch and h.status == HandoffStatus.AWAITING for h in shop))
        owner = Handoff.objects.get(step=HandoffStep.COMPANY_TO_OWNER)
        self.assertEqual(owner.status, HandoffStatus.AWAITING)

    def test_commission_rent_change_transfer_and_leaver(self):
        seed()
        nxt = RentPeriod.current().next()
        javane = Contractor.objects.get(staff_id="1011")
        self.assertEqual(CommissionEarning.objects.filter(contractor=javane).count(), 2)
        self.assertEqual(pay_type_for(javane, nxt), "RENT")
        self.assertEqual(shop_for(Contractor.objects.get(staff_id="1017"), nxt).name, "UTech Barbershop")
        self.assertFalse(Contractor.objects.get(staff_id="1010").is_active)
        kemar = Contractor.objects.get(staff_id="1002")
        self.assertEqual(len(rent_settings.pending_rent_notices(kemar.user)), 1)

    def test_demo_phone_from_env_goes_on_kemar_only(self):
        seed(DEMO_PHONE="876-555-9999")
        kemar = Contractor.objects.get(staff_id="1002")
        self.assertEqual(kemar.phone, "876-555-9999")
        self.assertTrue(receipts.whatsapp_link(receipts.latest_receipt(kemar.payments.first()))
                        .startswith("https://wa.me/18765559999"))
        self.assertEqual(Contractor.objects.filter(phone="876-555-9999").count(), 1)

    def test_without_demo_phone_everyone_gets_made_up_numbers(self):
        seed()
        self.assertEqual(Contractor.objects.get(staff_id="1002").phone, "876-555-0101")
        self.assertEqual(Contractor.objects.get(staff_id="1017").phone, "")  # no phone (US-07 AC-3)
