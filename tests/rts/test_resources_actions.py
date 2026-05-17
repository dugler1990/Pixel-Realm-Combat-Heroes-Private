import pytest

from rts.actions import RtsActionDefinition, RtsActionQueue
from rts.resources import TribeResources


def test_resources_can_afford_and_spend_when_sufficient():
    resources = TribeResources({"gold": 50, "wood": 10})

    assert resources.can_afford({"gold": 25, "wood": 5})
    assert resources.spend({"gold": 25, "wood": 5})
    assert resources.get("gold") == 25
    assert resources.get("wood") == 5


def test_resources_reject_spend_when_insufficient():
    resources = TribeResources({"gold": 10})

    assert not resources.can_afford({"gold": 25})
    assert not resources.spend({"gold": 25})
    assert resources.get("gold") == 10


def test_action_definition_from_dict_fills_defaults_and_cost():
    action = RtsActionDefinition.from_dict(
        "produce_spearman",
        {
            "type": "produce_unit",
            "description": "Train a basic melee unit.",
            "cost": {"gold": 25},
            "duration_ms": 5000,
            "payload": {"unit_id": "tribey_spear"},
        },
    )

    assert action.action_id == "produce_spearman"
    assert action.label == "Produce Spearman"
    assert action.action_type == "produce_unit"
    assert action.description == "Train a basic melee unit."
    assert action.cost == {"gold": 25}
    assert action.duration_ms == 5000
    assert action.payload == {"unit_id": "tribey_spear"}


def test_action_availability_uses_resource_wallet():
    action = RtsActionDefinition("upgrade", "Upgrade", cost={"gold": 100})

    assert action.is_available(TribeResources({"gold": 100}))
    assert not action.is_available(TribeResources({"gold": 99}))
    assert action.is_available(None)


def test_action_queue_reports_progress_and_completion():
    queue = RtsActionQueue()
    action = RtsActionDefinition("train", "Train", duration_ms=1000)

    queue.start(action)

    assert queue.current is action
    assert queue.progress() == 0.0
    assert queue.update(0.25) is None
    assert queue.progress() == pytest.approx(0.25)

    finished = queue.update(0.75)

    assert finished is action
    assert queue.current is None
    assert queue.progress() == 0.0


def test_action_queue_completes_zero_duration_immediately():
    queue = RtsActionQueue()
    action = RtsActionDefinition("instant", "Instant", duration_ms=0)

    queue.start(action)

    assert queue.update(0.0) is action
    assert queue.current is None
