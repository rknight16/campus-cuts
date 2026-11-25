"""US-03 page tests: the handoff forms guard against the wrong week, a future date and typing the amount blind."""
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from rent.models import Handoff, HandoffStatus, HandoffStep, Payment, RentPeriod
from rent.services.handoffs import record_shop_handoff
from rent.tests.helpers import PASSWORD, make_world

TODAY = date(2026, 11, 4)  # Wednesday inside the rent period 2 to 8 Nov 2026


class HandoffPageTestCase(TestCase):
    def setUp(self):
        patcher = patch("django.utils.timezone.localdate", return_value=TODAY)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.w = make_world()
        self.url = reverse("handoffs")

    def pay(self, amount, contractor=None):
        Payment.objects.create(
            contractor=contractor or self.w.taylor_c, rent_period=self.w.period, amount=Decimal(amount),
            payment_date=TODAY, recorded_by=self.w.taylor_sup.user,
        )

    def shop_form(self):
        self.client.force_login(self.w.taylor_sup.user)
        return self.client.get(self.url).context["shop_form"]


class ShopHandoffFormTests(HandoffPageTestCase):
    def test_future_weeks_are_not_offered(self):
        future = self.w.period.next()  # the rent settings page creates next week's period
        periods = list(self.shop_form().fields["period"].queryset)
        self.assertNotIn(future, periods)
        self.assertEqual(periods[0], self.w.period)

    def test_weeks_already_handed_over_are_not_offered(self):
        last_week = RentPeriod.for_date(TODAY - timedelta(days=7))
        record_shop_handoff(shop=self.w.taylor, period=last_week, amount=Decimal("100"),
                            handed_date=TODAY, handed_by=self.w.taylor_sup.user)
        periods = list(self.shop_form().fields["period"].queryset)
        self.assertNotIn(last_week, periods)
        self.assertIn(self.w.period, periods)

    def test_starts_on_the_newest_week_with_todays_date(self):
        form = self.shop_form()
        self.assertEqual(form.initial["period"], self.w.period.pk)
        self.assertEqual(form.initial["handed_date"], TODAY)
        self.assertEqual(form.fields["handed_date"].widget.attrs["max"], "2026-11-04")

    def test_amount_starts_at_the_rent_recorded_for_the_week(self):
        self.pay(15000)
        self.pay(15000, self.w.taylor_sup)
        self.client.force_login(self.w.taylor_sup.user)
        response = self.client.get(self.url)
        self.assertEqual(response.context["shop_form"].initial["amount"], 30000)
        self.assertContains(response, "You recorded <strong data-expected-amount>$30,000</strong>")
        self.assertContains(response, 'data-expected="30000.00"')

    def test_current_week_is_labelled_and_the_blank_choice_reads_as_words(self):
        self.client.force_login(self.w.taylor_sup.user)
        response = self.client.get(self.url)
        self.assertContains(response, "(this week)")
        self.assertContains(response, "Choose a rent period")
        self.assertNotContains(response, "---------")

    def test_future_date_error_shows_under_the_date_field(self):
        self.client.force_login(self.w.taylor_sup.user)
        response = self.client.post(self.url, {
            "action": "record_shop", "period": self.w.period.pk, "amount": "100",
            "handed_date": (TODAY + timedelta(days=1)).isoformat(),
        })
        self.assertContains(response, 'id="id_handed_date-error"')
        self.assertContains(response, 'aria-invalid="true"')
        self.assertFalse(Handoff.objects.exists())

    def test_all_weeks_handed_over_shows_a_done_message(self):
        RentPeriod.objects.exclude(pk=self.w.period.pk).delete()
        record_shop_handoff(shop=self.w.taylor, period=self.w.period, amount=Decimal("100"),
                            handed_date=TODAY, handed_by=self.w.taylor_sup.user)
        self.client.force_login(self.w.taylor_sup.user)
        self.assertContains(self.client.get(self.url), "Every recent rent period has been handed over.")


class ConfirmRowTests(HandoffPageTestCase):
    def test_confirm_input_knows_the_amount_handed_over(self):
        Handoff.objects.create(
            step=HandoffStep.SHOP_TO_COMPANY, shop=self.w.taylor, rent_period=self.w.period,
            expected_amount=Decimal("15000"), amount_handed=Decimal("15000"), handed_date=TODAY,
            handed_by=self.w.taylor_sup.user, status=HandoffStatus.AWAITING,
        )
        self.client.force_login(self.w.company)
        response = self.client.get(self.url)
        self.assertContains(response, 'data-expected="15000.00"')
        self.assertContains(response, "needs-action")

    def test_confirm_asks_are_you_sure_first(self):
        # DEF-3-01: SF-3 says the user must confirm before a handoff is confirmed
        Handoff.objects.create(
            step=HandoffStep.SHOP_TO_COMPANY, shop=self.w.taylor, rent_period=self.w.period,
            expected_amount=Decimal("15000"), amount_handed=Decimal("15000"), handed_date=TODAY,
            handed_by=self.w.taylor_sup.user, status=HandoffStatus.AWAITING,
        )
        self.client.force_login(self.w.company)
        response = self.client.get(self.url)
        self.assertContains(response, "return confirm('Are you sure you want to confirm this handoff?')")


class LoginTests(TestCase):
    def test_failed_login_keeps_the_username(self):
        make_world()
        response = self.client.post(reverse("login"), {"username": "taylorsup", "password": PASSWORD + "x"})
        self.assertContains(response, 'value="taylorsup"')


class WaitingFirstTests(HandoffPageTestCase):
    """The Company Supervisor's confirm job comes before the outgoing form, with a one-tap exact confirm."""

    def setUp(self):
        super().setUp()
        self.handoff = Handoff.objects.create(
            step=HandoffStep.SHOP_TO_COMPANY, shop=self.w.taylor, rent_period=self.w.period,
            expected_amount=Decimal("15000"), amount_handed=Decimal("15000"), handed_date=TODAY,
            handed_by=self.w.taylor_sup.user, status=HandoffStatus.AWAITING,
        )
        self.client.force_login(self.w.company)

    def test_waiting_handoffs_come_before_the_record_form(self):
        response = self.client.get(self.url)
        html = response.content.decode()
        self.assertEqual(response.context["waiting"], [self.handoff])
        self.assertLess(html.index('id="waiting"'), html.index("data-handoff-form"))
        self.assertFalse(response.context["form_open"])
        self.assertNotIn("{#", html)  # no template comment leaks onto the page

    def test_received_exactly_confirms_the_amount_handed_over(self):
        self.client.post(self.url, {"action": "confirm", "handoff_id": self.handoff.pk, "received_exact": "1"})
        self.handoff.refresh_from_db()
        self.assertEqual(self.handoff.status, HandoffStatus.CONFIRMED)
        self.assertEqual(self.handoff.amount_received, Decimal("15000"))

    def test_a_different_amount_still_works(self):
        self.client.post(self.url, {"action": "confirm", "handoff_id": self.handoff.pk, "amount_received": "14000"})
        self.handoff.refresh_from_db()
        self.assertEqual(self.handoff.amount_received, Decimal("14000"))

    def test_record_form_is_open_when_nothing_is_waiting(self):
        self.handoff.status = HandoffStatus.CONFIRMED
        self.handoff.amount_received = Decimal("15000")
        self.handoff.save()
        self.assertTrue(self.client.get(self.url).context["form_open"])
