from __future__ import annotations

import json

from faultline.live import OpenRouterInvestigatorController


def test_investigator_controller_preserves_initial_hypothesis_context(monkeypatch) -> None:
    controller = OpenRouterInvestigatorController("nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free", api_key="test")
    captured: dict[str, object] = {}

    def fake_request(messages, response_format):
        captured["messages"] = messages
        return {"kind": "finish"}

    monkeypatch.setattr(controller, "_request", fake_request)
    observations = [{"kind": "hypotheses", "hypothesis_id": "initial-hypothesis"}] + [{"kind": "experiment", "trial_id": str(index)} for index in range(20)]
    action = controller.next_action(observations)

    assert action.kind == "finish"
    user_message = captured["messages"][1]["content"]  # type: ignore[index]
    payload = json.loads(user_message)
    assert payload["observations"][0]["hypothesis_id"] == "initial-hypothesis"
    assert len(payload["observations"]) == len(observations)
