"""ContractorService (US-05) - owner: Jordon Stewart

add / update / transfer / deactivate contractors, set the Shop Supervisor
(previous one loses the role, AC-5), create the Company Supervisor account.
Creating a contractor also creates their User login (role CONTRACTOR).
"""


def add_contractor(*, full_name, staff_id, shop, phone="", photo=None, pay_type="RENT", password=None):
    raise NotImplementedError


def set_shop_supervisor(*, shop, contractor):
    raise NotImplementedError


def transfer(*, contractor, new_shop):
    raise NotImplementedError


def deactivate(*, contractor):
    raise NotImplementedError
