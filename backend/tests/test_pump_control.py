from datetime import UTC, datetime, timedelta
from decimal import Decimal

from evolver.ingestion.control import action_for_od, is_fresh_od


def test_two_hysteresis_cycles_and_equal_limits() -> None:
    minimum, maximum = Decimal("0.125"), Decimal("0.7")
    state = "off"
    actions = []
    for value in ("0.4", "0.7", "0.4", "0.125", "0.4", "0.8", "0.3", "0.1"):
        action = action_for_od(state, Decimal(value), minimum, maximum)
        if action:
            actions.append(action)
            state = "on" if action == "turn_on" else "off"
    assert actions == ["turn_on", "turn_off", "turn_on", "turn_off"]


def test_unknown_state_never_causes_a_transition() -> None:
    assert action_for_od("unknown", Decimal("0.8"), Decimal("0.1"), Decimal("0.7")) is None


def test_freshness_boundary() -> None:
    now = datetime.now(UTC)
    assert is_fresh_od(now, now)
    assert is_fresh_od(now - timedelta(seconds=10), now)
    assert not is_fresh_od(now - timedelta(seconds=11), now)
    assert not is_fresh_od(now + timedelta(seconds=1), now)
