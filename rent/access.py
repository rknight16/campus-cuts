"""
Access control (SE-2): role and shop checks, done on the server for every view.

Use these on EVERY view you write. Never rely on hiding a link in the page;
someone can always type the web address (UC-04 A4, UC-06 A4, US-07 AC-5).

    from rent.access import role_required, ensure_same_shop, ensure_own_contractor
    from rent.models import Role

    @role_required(Role.SHOP_SUPERVISOR)
    def record_payment(request, contractor_id):
        contractor = get_object_or_404(Contractor, pk=contractor_id)
        ensure_same_shop(request.user, contractor.shop)   # 403 if another shop
        ...
"""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from .models import Role


def role_required(*roles):
    """Allow the view only for logged-in users whose role is in `roles`.

    Anyone else gets 403 Forbidden, even if they type the URL directly.
    """
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapper(request, *args, **kwargs):
            if request.user.role not in roles:
                raise PermissionDenied("Your role cannot open this page.")
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


def contractor_required(view_func):
    """Allow only users who pay rent (independent contractors and Shop Supervisors)."""
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_contractor:
            raise PermissionDenied("Only independent contractors have a rent account.")
        return view_func(request, *args, **kwargs)
    return wrapper


def ensure_same_shop(user, shop):
    """A Shop Supervisor may only act on their own shop (US-01 AC-5).

    Owner and Company Supervisor can see every shop.
    """
    if user.role in (Role.OWNER, Role.COMPANY_SUPERVISOR):
        return
    if user.role == Role.SHOP_SUPERVISOR and user.supervised_shop == shop:
        return
    raise PermissionDenied("You can only see your own shop.")


def ensure_own_contractor(user, contractor):
    """An independent contractor may only see their own account (US-06 AC-4, US-07 AC-5)."""
    if getattr(user, "contractor_profile", None) == contractor:
        return
    raise PermissionDenied("You can only see your own account.")


def contractors_visible_to(user):
    """Queryset of contractors this user may see in lists."""
    from .models import Contractor
    qs = Contractor.objects.select_related("shop", "user")
    if user.role in (Role.OWNER, Role.COMPANY_SUPERVISOR):
        return qs
    if user.role == Role.SHOP_SUPERVISOR:
        return qs.filter(shop=user.supervised_shop)
    return qs.filter(user=user)
