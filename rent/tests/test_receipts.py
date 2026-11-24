"""US-07 Send a payment receipt on WhatsApp: tests named after the SRS scenarios."""
from datetime import date
from decimal import Decimal
from unittest.mock import patch
from urllib.parse import unquote

from django.test import TestCase
from django.urls import reverse

from rent.formatting import format_money
from rent.models import Receipt
from rent.services import payments, receipts
from rent.tests.helpers import make_world

TODAY = date(2026, 11, 4)  # Wednesday inside the rent period 2 to 8 Nov 2026


class ReceiptTestCase(TestCase):
    def setUp(self):
        patcher = patch("django.utils.timezone.localdate", return_value=TODAY)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.w = make_world()
        self.sup = self.w.taylor_sup.user
        self.c = self.w.taylor_c
        self.c.phone = "876-555-0123"
        self.c.save()

    def pay(self, amount="10000", contractor=None, by=None):
        return payments.record_payment(
            contractor=contractor or self.c, period=self.w.period, amount=amount,
            payment_date=TODAY, recorded_by=by or self.sup,
        )

    def receipt_for(self, payment):
        return receipts.latest_receipt(payment)

    def open_page(self, user, receipt):
        self.client.force_login(user)
        return self.client.get(reverse("receipt_detail", args=[receipt.pk]))


class ReceiptCreationTests(ReceiptTestCase):
    def test_ac1_receipt_for_a_part_payment(self):
        payment = self.pay("10000")  # $10,000 of the $15,000 owed
        d = receipts.receipt_details(self.receipt_for(payment))
        self.assertEqual(d["amount"], Decimal("10000"))
        self.assertEqual(d["balance"], Decimal("5000"))
        self.assertEqual(len(d["number"]), 6)
        self.assertEqual(d["shop"], self.w.taylor)
        self.assertEqual(d["contractor"], self.c)
        self.assertEqual(d["period"], self.w.period)
        self.assertEqual(d["payment_date"], TODAY)
        self.assertEqual(d["received_by"], self.sup)
        self.assertFalse(d["is_corrected"])

    def test_ac1_balance_reaches_zero_when_paid_in_full(self):
        self.pay("10000")
        second = self.pay("5000")
        self.assertEqual(self.receipt_for(second).balance_after, Decimal("0"))

    def test_every_saved_payment_gets_its_own_receipt(self):
        self.pay("10000")
        self.pay("5000")
        self.assertEqual(Receipt.objects.count(), 2)


class WhatsAppTests(ReceiptTestCase):
    def test_ac2_link_opens_whatsapp_for_the_contractor_with_the_receipt_typed(self):
        receipt = self.receipt_for(self.pay("10000"))
        link = receipts.whatsapp_link(receipt)
        self.assertTrue(link.startswith("https://wa.me/18765550123?text="))
        text = unquote(link.split("?text=", 1)[1])
        self.assertIn(f"RENT RECEIPT {receipt.number}", text)
        self.assertIn(self.c.full_name, text)
        self.assertIn(format_money(Decimal("10000")), text)
        self.assertIn(format_money(Decimal("5000")), text)

    def test_ac2_supervisor_sees_the_send_button(self):
        response = self.open_page(self.sup, self.receipt_for(self.pay()))
        self.assertContains(response, "Send on WhatsApp")
        self.assertContains(response, "wa.me/18765550123")

    def test_ac3_contractor_has_no_phone_number(self):
        self.c.phone = ""
        self.c.save()
        receipt = self.receipt_for(self.pay())
        self.assertIsNone(receipts.whatsapp_link(receipt))
        response = self.open_page(self.sup, receipt)
        self.assertContains(response, "phone number is needed")
        self.assertNotContains(response, "wa.me")
        # the receipt is still saved
        self.assertEqual(Receipt.objects.count(), 1)


class CorrectedReceiptTests(ReceiptTestCase):
    def correct(self, payment, new_amount="12000"):
        return payments.correct_payment(
            payment=payment, new_amount=new_amount, new_payment_date=TODAY,
            reason="Typing error", corrected_by=self.sup,
        )

    def test_ac4_receipt_after_a_correction(self):
        payment = self.pay("10000")
        original = self.receipt_for(payment)
        self.correct(payment, "12000")

        self.assertEqual(Receipt.objects.filter(payment=payment).count(), 2)
        new = self.receipt_for(payment)
        self.assertNotEqual(new.pk, original.pk)
        self.assertTrue(new.is_corrected)
        self.assertEqual(new.corrects, original)

        d_new = receipts.receipt_details(new)
        self.assertEqual(d_new["amount"], Decimal("12000"))
        self.assertEqual(d_new["balance"], Decimal("3000"))
        self.assertEqual(d_new["corrects_number"], original.number)

    def test_ac4_original_receipt_is_kept_unchanged(self):
        payment = self.pay("10000")
        original = self.receipt_for(payment)
        self.correct(payment, "12000")
        d_old = receipts.receipt_details(Receipt.objects.get(pk=original.pk))
        self.assertEqual(d_old["amount"], Decimal("10000"))
        self.assertEqual(d_old["balance"], Decimal("5000"))
        self.assertFalse(d_old["is_corrected"])

    def test_ac4_corrected_receipt_text_refers_to_the_original(self):
        payment = self.pay("10000")
        original = self.receipt_for(payment)
        self.correct(payment)
        text = receipts.receipt_text(self.receipt_for(payment))
        self.assertIn("CORRECTED", text)
        self.assertIn(f"replaces receipt {original.number}", text)


class ReceiptAccessTests(ReceiptTestCase):
    def test_ac5_contractor_opens_their_own_receipt(self):
        receipt = self.receipt_for(self.pay())
        response = self.open_page(self.c.user, receipt)
        self.assertEqual(response.status_code, 200)
        # only the supervisor sends it
        self.assertNotContains(response, "wa.me")

    def test_ac5_contractor_opens_someone_elses_receipt(self):
        receipt = self.receipt_for(self.pay())
        self.assertEqual(self.open_page(
            self.w.utech_c.user, receipt).status_code, 403)

    def test_supervisor_of_another_shop_is_denied(self):
        receipt = self.receipt_for(self.pay())
        self.assertEqual(self.open_page(
            self.w.utech_sup.user, receipt).status_code, 403)

    def test_owner_and_company_supervisor_are_denied(self):
        receipt = self.receipt_for(self.pay())
        for user in (self.w.owner, self.w.company):
            with self.subTest(user=user.username):
                self.assertEqual(self.open_page(
                    user, receipt).status_code, 403)

    def test_receipts_list_shows_only_the_supervisors_own_shop(self):
        self.pay("10000")
        self.client.force_login(self.w.taylor_sup.user)
        self.assertContains(self.client.get(
            reverse("receipts")), self.c.full_name)
        self.client.force_login(self.w.utech_sup.user)
        self.assertNotContains(self.client.get(
            reverse("receipts")), self.c.full_name)

    def test_receipts_list_is_for_shop_supervisors_only(self):
        self.client.force_login(self.c.user)
        self.assertEqual(self.client.get(reverse("receipts")).status_code, 403)

    def test_ac5_contractor_finds_the_receipt_in_their_payment_history(self):
        receipt = self.receipt_for(self.pay())
        self.client.force_login(self.c.user)
        response = self.client.get(reverse("my_account"))
        self.assertContains(response, reverse(
            "receipt_detail", args=[receipt.pk]))
        self.assertContains(response, receipt.number)
