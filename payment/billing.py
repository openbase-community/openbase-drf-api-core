from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from payment.models import Subscription

User = get_user_model()


def user_has_active_subscription(user: User) -> bool:
    """Return True when the user has an active personal or team subscription."""
    if not user or not user.is_authenticated:
        return False

    now = timezone.now()
    return Subscription.objects.filter(
        Q(account__user_owner=user) | Q(account__team_owner__owner=user),
        expiration_date__gt=now,
    ).exists()


def require_within_hard_cap(
    *,
    current_count: int,
    cap: int,
    detail: str,
) -> None:
    # `cap <= 0` disables creation for that resource.
    if cap <= 0 or current_count >= cap:
        raise PermissionDenied(detail=detail)
