from typing import Any

import httpx
import pytest

from scripts.live_provider_checks import require_unlimited_runs

NO_LIMITS = {
    "rules": None,
    "connected_accounts": None,
    "integration_tokens": None,
    "sync_interval": "instant",
}
"""The limits of the No limits Plan, as Your plan answers them."""


def _signed_in(basis: str, limits: dict[str, Any] | None = None) -> httpx.Client:
    """An API whose Your plan answers the basis and limits, and which knows no other route."""

    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.path != "/api/v1/account/plan":
            return httpx.Response(404)
        return httpx.Response(200, json={"basis": basis, "limits": limits})

    return httpx.Client(
        base_url="http://calendar-ghost.test", transport=httpx.MockTransport(answer)
    )


@pytest.mark.parametrize(
    ("basis", "limits"),
    [("plans_off", None), ("administrator", None), ("plan", NO_LIMITS)],
    ids=["plans off", "administrator", "no limits plan"],
)
def test_the_checks_run_for_a_user_whose_manual_runs_are_not_counted(
    basis: str, limits: dict[str, Any] | None
) -> None:
    require_unlimited_runs(_signed_in(basis, limits))


def test_the_checks_stop_before_anything_when_a_plan_limits_the_user() -> None:
    # One run of the checks starts more manual runs than the limit allows in an hour.
    with pytest.raises(SystemExit, match="sign in as an administrator, or turn Plans off"):
        require_unlimited_runs(_signed_in("plan", {**NO_LIMITS, "sync_interval": "60_minutes"}))
