"""Subscription-lifecycle hooks contributed by consuming app packages.

api-core must stay reusable across projects, so it cannot import consuming
apps to tear down their resources when a subscription ends. Instead, app
packages register callables under the ``api_core.subscription_cancellation_hooks``
entry-point group:

    [project.entry-points."api_core.subscription_cancellation_hooks"]
    my_app = "my_package.subscription_hooks:on_subscription_cancellation"

Each hook receives the owning user and returns a mapping of counter names to
counts describing what it cleaned up (used for logging only). Hooks must be
idempotent: a failure surfaces as a 5xx on the webhook, the payment provider
redelivers, and every hook runs again.
"""

import functools
import importlib.metadata


@functools.cache
def subscription_cancellation_hooks() -> tuple:
    entry_points = importlib.metadata.entry_points()
    return tuple(
        entry_point.load()
        for entry_point in entry_points.select(
            group="api_core.subscription_cancellation_hooks"
        )
    )


def run_subscription_cancellation_hooks(user) -> dict[str, int]:
    result: dict[str, int] = {}
    for hook in subscription_cancellation_hooks():
        result.update(hook(user))
    return result
