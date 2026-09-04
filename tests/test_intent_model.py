"""Learned intent classifier (ADR-0015): contract gates over the SHIPPED model.

The hand-written set here is deliberately independent of the synthetic
training corpus — it is the honesty check on the trainer's own eval numbers.
The structural invariant under test: the model can only ever propose
engine-legal intent text (the real matchers dispose), never execute.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from conftest import FakeProvider
from jarvis.cli.app import main
from jarvis.intent import classifier as classifier_module
from jarvis.intent.classifier import (
    MODEL_FORMAT,
    UNKNOWN_LABEL,
    classify,
    load_model,
    rank_intents,
    suggest_intent,
)
from jarvis.journal.sqlite import default_db_path, state_dir
from jarvis.planner.playbooks import match_intent

# ---------------------------------------------------------------------------
# artifact + structural contract
# ---------------------------------------------------------------------------


def test_model_artifact_shape() -> None:
    raw = (classifier_module.resources.files("jarvis.intent") / "model.json").read_text(
        encoding="utf-8"
    )
    document = json.loads(raw)
    assert document["format"] == MODEL_FORMAT
    assert document["labels"][-1] == UNKNOWN_LABEL
    assert len(document["w1"]) == 256 and len(document["w1"][0]) == 48
    assert len(document["w2"]) == 48
    size_kb = len(raw) / 1024
    assert size_kb < 400  # the model must stay tiny (ADR-0015)


def test_every_suggestion_is_engine_legal() -> None:
    for text, _label in HAND_LABELED:
        suggestion = suggest_intent(text)
        if suggestion is not None:
            assert match_intent(suggestion) is not None, f"{text!r} -> {suggestion!r}"


def test_deterministic_and_fast() -> None:
    started = time.monotonic()
    for _ in range(20):
        first = classify("can you install htop for me")
        second = classify("can you install htop for me")
        assert first == second
    assert time.monotonic() - started < 5.0  # 20 inferences, generous bound


def test_missing_model_falls_back_to_no_proposal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(classifier_module, "load_model", lambda: None)
    assert rank_intents("install htop") == []
    assert suggest_intent("can you install htop for me") is None


# ---------------------------------------------------------------------------
# hand-written labeled set (independent of the training generator)
# ---------------------------------------------------------------------------

HAND_LABELED: list[tuple[str, str]] = [
    ("can you install htop for me", "pkg.install"),
    ("i need vim on this machine", "pkg.install"),
    ("please get ripgrep onto this box", "pkg.install"),
    ("please get rid of curl", "pkg.remove"),
    ("uninstall vlc from my system", "pkg.remove"),
    ("is there a good pdf reader available", "pkg.search"),
    ("find me a markdown editor", "pkg.search"),
    ("tell me about the git package", "pkg.info"),
    ("show details for openssl", "pkg.info"),
    ("refresh the package lists", "pkg.cache.refresh"),
    ("update the package index", "pkg.cache.refresh"),
    ("bring my system up to date", "pkg.upgrade"),
    ("update everything", "pkg.upgrade"),
    ("is nginx running", "svc.status"),
    ("what's the status of the docker service", "svc.status"),
    ("start the docker service", "svc.start"),
    ("enable redis at boot", "svc.enable"),
    ("what distro am i on", "sys.info"),
    ("show me the hardware details", "sys.info"),
    ("open firefox", "gui.launch"),
    ("launch the calculator app", "gui.launch"),
    ("append remember the milk to ~/notes.txt", "file.append"),
]

HAND_OOD: list[str] = [
    "what's the weather in paris",
    "tell me a joke",
    "how do i exit vim",
    "when is my next meeting",
    "write a poem about the sea",
    "why is my computer slow",
]


def test_hand_labeled_top1_accuracy() -> None:
    correct = sum(
        1
        for text, label in HAND_LABELED
        if (distribution := classify(text)) and max(distribution, key=distribution.get) == label
    )
    assert correct / len(HAND_LABELED) >= 0.9, f"{correct}/{len(HAND_LABELED)}"


def test_hand_labeled_top3_recall() -> None:
    hits = sum(
        1
        for text, label in HAND_LABELED
        if label in [candidate for candidate, _prob in rank_intents(text, k=3)]
    )
    assert hits == len(HAND_LABELED), f"{hits}/{len(HAND_LABELED)} in top-3"


def test_hand_ood_abstains_from_suggestions() -> None:
    abstained = sum(1 for text in HAND_OOD if suggest_intent(text) is None)
    assert abstained / len(HAND_OOD) >= 0.85, f"{abstained}/{len(HAND_OOD)}"


def test_file_append_has_no_slot_extractor() -> None:
    # Deliberate: paths are not reconstructed from model output — disclosure only.
    assert suggest_intent("append remember the milk to ~/notes.txt") is None


def test_canonical_suggestions() -> None:
    assert suggest_intent("can you install htop for me") == "install htop"
    assert suggest_intent("please get rid of curl") == "remove curl"
    assert suggest_intent("is nginx running") == "status of nginx"
    assert suggest_intent("refresh the package lists") == "update the package cache"


# ---------------------------------------------------------------------------
# end-to-end wiring (proposals-only, --no-ai honored)
# ---------------------------------------------------------------------------


def _force_no_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:1")  # nothing listens there
    monkeypatch.setenv("JARVIS_REMOTE_LLM", "0")


def test_nn_suggestion_surfaces_in_unknown_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    _force_no_backend(monkeypatch)
    code = main(["--json", "ask", "can you install htop for me"])
    assert code == 2
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "refused"
    assert data["error"].startswith("unknown-request")
    assert "jarvis do install htop" in data["hint"]
    assert "never self-execute" in data["hint"]
    assert "did you mean" in data["hint"]


def test_no_ai_switches_the_classifier_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    _force_no_backend(monkeypatch)
    code = main(["--json", "--no-ai", "ask", "can you install htop for me"])
    assert code == 2
    data = json.loads(capsys.readouterr().out)
    assert "jarvis do" not in data["hint"]  # no learned proposal
    assert "did you mean" in data["hint"]  # lexical disclosure still present


def test_unexpressible_planner_answer_gets_nn_suggestion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    _force_no_backend(monkeypatch)
    # A provider IS configured, but it honestly reports the request as
    # unexpressible; the classifier then proposes for the disclosure layer.
    provider = FakeProvider(['{"explanation": "cannot", "steps": []}'])
    monkeypatch.setattr(
        "jarvis.cli.app.plan_routing",
        lambda env=None, enabled=True: __import__(
            "jarvis.providers.router", fromlist=["Routing"]
        ).Routing("local", provider, "test"),
    )
    code = main(["--json", "ask", "can you install htop for me"])
    assert code == 2
    data = json.loads(capsys.readouterr().out)
    assert "jarvis do install htop" in data["hint"]
    # the honest "unexpressible" must not trip the breaker
    from jarvis.providers.breaker import ProviderBreaker

    assert ProviderBreaker(state_dir() / "ai" / "breaker.state").views() == {}


def test_engine_match_never_consults_the_classifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(classifier_module, "load_model", lambda: None)  # no model at all
    code = main(["--json", "do", "--dry-run", "install", "htop"])
    assert code == 0  # engine-first: dry run works with zero model present
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "dry_run"


def test_model_file_ships_via_state_dir_independent_path() -> None:
    # The weights load from package data regardless of JARVIS_STATE_DIR.
    assert load_model() is not None
    assert default_db_path().name == "journal.db"
