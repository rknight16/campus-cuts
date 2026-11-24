"""US-02 page tests: the rent settings page and the rent-change notice after login."""
from datetime import date
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from rent.models import RentSetting, Weekday
from rent.services import rent_settings
from rent.tests.helpers import make_world

TODAY = date(2026, 11, 4)  # Wednesday inside the rent period 2 to 8 Nov 2026


class PageTestCase(TestCase):
    def setUp(self):
        patcher = patch("django.utils.timezone.localdate", return_value=TODAY)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.w = make_world()


class RentSettingsPageTests(PageTestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse("rent_settings")
        self.client.force_login(self.w.owner)

    def post(self, **data):
        form = {"shop": self.w.taylor.pk, "weekly_rent": "15000", "due_day": "4"}
        form.update(data)
        return self.client.post(self.url, form)

    def test_ac1_owner_sees_save_successful(self):
        response = self.post()
        self.assertContains(response, "Save Successful")

    def test_ac2_zero_rent_shows_invalid_and_saves_nothing(self):
        before = RentSetting.objects.count()
        response = self.post(weekly_rent="0")
        self.assertContains(response, "The amount is invalid.")
        self.assertNotContains(response, "Save Successful")
        self.assertEqual(RentSetting.objects.count(), before)

    def test_ac2_missing_due_day_shows_a_message(self):
        response = self.post(due_day="")
        self.assertContains(response, "Select a due day.")

    def test_missing_shop_shows_a_message(self):
        response = self.post(shop="")
        self.assertContains(response, "Select a shop.")

    def test_only_the_owner_can_open_the_page(self):
        for user in (self.w.company, self.w.taylor_sup.user, self.w.taylor_c.user):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                self.assertEqual(self.client.get(self.url).status_code, 403)
                self.assertEqual(self.client.post(self.url, {}).status_code, 403)


class LoginNoticeTests(PageTestCase):
    def owner_raises_taylor_rent(self):
        rent_settings.set_rent(
            shop=self.w.taylor, weekly_rent="16000",
            due_day=Weekday.FRIDAY, set_by=self.w.owner,
        )

    def log_in_and_land(self, user):
        self.client.force_login(user)
        return self.client.get(reverse("home"), follow=True)

    def test_ac5_shop_supervisor_is_told_about_the_new_rent_on_login(self):
        self.owner_raises_taylor_rent()
        response = self.log_in_and_land(self.w.taylor_sup.user)
        self.assertContains(response, "Rent at UWI Taylor Hall is changing to $16,000.00")
        self.assertContains(response, "9 Nov 2026")

    def test_ac5_company_supervisor_is_told_too(self):
        self.owner_raises_taylor_rent()
        response = self.log_in_and_land(self.w.company)
        self.assertContains(response, "Rent at UWI Taylor Hall is changing to $16,000.00")

    def test_ac5_notice_shows_once_per_login(self):
        self.owner_raises_taylor_rent()
        self.log_in_and_land(self.w.taylor_sup.user)
        response = self.client.get(reverse("home"), follow=True)
        self.assertNotContains(response, "is changing to")

    def test_ac5_no_notice_when_the_rent_has_not_changed(self):
        response = self.log_in_and_land(self.w.taylor_sup.user)
        self.assertNotContains(response, "is changing to")