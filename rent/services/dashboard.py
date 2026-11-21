"""DashboardService (US-04) - owner: Dylandre Henry

Read-only summary for the Owner and Company Supervisor. Uses rent_rules for
owed/paid/balance/overdue per shop and lists each shop's handoff status.
Every shop is listed, even with $0 paid (AC-4).
"""


def shop_summary(period=None):
    raise NotImplementedError
