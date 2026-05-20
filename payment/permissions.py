from rest_framework.permissions import BasePermission

from payment.billing import user_has_active_subscription


class HasActiveSubscription(BasePermission):
    message = "An active subscription is required."

    def __init__(self, message: str | None = None):
        if message is not None:
            self.message = message

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user and user.is_authenticated and user_has_active_subscription(user)
        )
