"""US-02 Set weekly rent and due day: tests for rent/services/rent_settings.py.

Each test is named after the SRS scenario it checks (AC number first).
"Today" is fixed to Wednesday 4 November 2026, the day used in the AC-4 scenario.
"""
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from rent.models import RentPeriod, RentSetting, Weekday
from rent.services import rent_settings
from rent.tests.helpers import make_world

TODAY = date(2026, 11, 4)         # Wednesday, inside the rent period 2 to 8 Nov 2026
NEXT_MONDAY = date(2026, 11, 9)   # start of the next rent period


class RentSettingsTests(TestCase):
    def setUp(self):
        patcher = patch("django.utils.timezone.localdate", return_value=TODAY)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.w = make_world()

    def save_rent(self, weekly_rent="16000", due_day=Weekday.FRIDAY, user=None, shop=None):
        return rent_settings.set_rent(
            shop=shop or self.w.taylor,
            weekly_rent=weekly_rent,
            due_day=due_day,
            set_by=user or self.w.owner,
        )

    def assert_rejected(self, message_part, **kwargs):
        before = RentSetting.objects.count()
        with self.assertRaises(ValidationError) as ctx:
            self.save_rent(**kwargs)
        self.assertIn(message_part, ctx.exception.messages[0])
        self.assertEqual(RentSetting.objects.count(), before)  # nothing saved

    # --- AC-1 ---------------------------------------------------------------
    def test_ac1_owner_sets_the_rent_for_a_shop(self):
        setting = self.save_rent(weekly_rent="15000", due_day=Weekday.FRIDAY)
        saved = RentSetting.objects.get(pk=setting.pk)
        self.assertEqual(saved.shop, self.w.taylor)
        self.assertEqual(saved.weekly_rent, Decimal("15000.00"))
        self.assertEqual(saved.due_day, Weekday.FRIDAY)
        self.assertEqual(saved.created_by, self.w.owner)

    def test_only_the_owner_can_set_the_rent(self):
        with self.assertRaises(PermissionDenied):
            self.save_rent(user=self.w.taylor_sup.user)

    # --- AC-2 ---------------------------------------------------------------
    def test_ac2_owner_enters_a_rent_of_zero(self):
        self.assert_rejected("invalid", weekly_rent="0")

    def test_ac2_owner_enters_a_negative_rent(self):
        self.assert_rejected("invalid", weekly_rent="-500")

    def test_ac2_owner_enters_a_rent_that_is_not_a_number(self):
        self.assert_rejected("invalid", weekly_rent="abc")

    def test_ac2_owner_leaves_the_rent_empty(self):
        for empty in ("", None):
            with self.subTest(value=empty):
                self.assert_rejected("invalid", weekly_rent=empty)

    def test_ac2_owner_does_not_select_a_due_day(self):
        for bad in (None, "", 9):
            with self.subTest(value=bad):
                self.assert_rejected("due day", due_day=bad)

    # --- AC-3 ---------------------------------------------------------------
    def test_ac3_due_date_for_a_new_rent_period(self):
        setting = RentSetting.for_shop(self.w.taylor, self.w.period)
        self.assertEqual(self.w.period.due_date_for(setting.due_day), date(2026, 11, 6))

    # --- AC-4 ---------------------------------------------------------------
    def test_ac4_owner_changes_the_rent_in_the_middle_of_a_week(self):
        self.save_rent(weekly_rent="16000")  # "today" is Wednesday 4 November
        next_period = RentPeriod.for_date(NEXT_MONDAY)
        self.assertEqual(RentSetting.for_shop(self.w.taylor, self.w.period).weekly_rent, Decimal("15000"))
        self.assertEqual(RentSetting.for_shop(self.w.taylor, next_period).weekly_rent, Decimal("16000"))

    def test_second_change_before_the_next_period_replaces_the_first(self):
        self.save_rent(weekly_rent="16000")
        self.save_rent(weekly_rent="17000")
        pending = RentSetting.objects.filter(shop=self.w.taylor, effective_from__start_date=NEXT_MONDAY)
        self.assertEqual(pending.count(), 1)
        self.assertEqual(pending.get().weekly_rent, Decimal("17000"))

    # --- AC-5 ---------------------------------------------------------------
    def test_ac5_contractor_sees_the_new_rent(self):
        self.save_rent(weekly_rent="16000", due_day=Weekday.FRIDAY)
        notices = rent_settings.pending_rent_notices(self.w.taylor_c.user)
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0]["weekly_rent"], Decimal("16000"))
        self.assertEqual(notices[0]["due_day"], "Friday")
        self.assertEqual(notices[0]["start_date"], NEXT_MONDAY)
        self.assertIn("9 Nov 2026", notices[0]["message"])

    def test_ac5_shop_supervisor_and_company_supervisor_also_see_it(self):
        self.save_rent(weekly_rent="16000")
        for user in (self.w.taylor_sup.user, self.w.company):
            with self.subTest(user=user.username):
                self.assertEqual(len(rent_settings.pending_rent_notices(user)), 1)

    def test_ac5_nobody_else_gets_a_notice(self):
        self.save_rent(weekly_rent="16000")
        for user in (self.w.utech_c.user, self.w.owner):
            with self.subTest(user=user.username):
                self.assertEqual(rent_settings.pending_rent_notices(user), [])

    def test_ac5_no_notice_when_the_rent_has_not_changed(self):
        self.assertEqual(rent_settings.pending_rent_notices(self.w.taylor_c.user), [])