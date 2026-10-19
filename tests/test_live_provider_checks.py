import httpx
import pytest

from scripts.live_provider_checks import require_unlimited_runs


def _signed_in(basis: str) -> httpx.Client:
    """An API whose Your plan answers the basis, and which knows no other route."""

    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.path != "/api/v1/account/plan":
            return httpx.Response(404)
        return httpx.Response(200, json={"basis": basis})

    return httpx.Client(
        base_url="http://calendar-ghost.test", transport=httpx.MockTransport(answer)
    )


@pytest.mark.parametrize("basis", ["plans_off", "administrator"])
def test_the_checks_run_for_a_user_whose_manual_runs_are_not_counted(basis: str) -> None:
    require_unlimited_runs(_signed_in(basis))


def test_the_checks_stop_before_anything_when_a_plan_limits_the_user() -> None:
    # One run of the checks starts more manual runs than the limit allows in an hour.
    with pytest.raises(SystemExit, match="sign in as an administrator, or turn Plans off"):
        require_unlimited_runs(_signed_in("plan"))
