"""Deterministic trainer for the tiny intent classifier (ADR-0015).

Pure-stdlib training for a purpose-built, JARVIS-specific network: hashed
n-gram features (vectorizer imported from the runtime module — single source
of truth), one 48-unit ReLU hidden layer, softmax over the playbook families
plus an explicit ``unknown`` class (the structural abstention).

Run from the repository root:

    python training/train_intent.py --out src/jarvis/intent/model.json

Deterministic: fixed seed, fixed op order → the committed model.json is
reproducible byte-for-byte. Gates are enforced before any weights are written:
top-1 >= 0.88 and top-3 >= 0.97 on a stratified holdout, unknown-recall
(abstention) >= 0.80 on an out-of-distribution pool. The trainer never runs at
runtime and is not part of the wheel — inference is the only shipped code.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jarvis.intent.classifier import (
    FEATURE_DIM,
    HIDDEN,
    MODEL_FORMAT,
    PROPOSE_THRESHOLD,
    UNKNOWN_LABEL,
    _features,
)

SEED = 20260904
EPOCHS = 12
LR = 0.35
LR_DECAY = 0.75

LABELS: list[str] = [
    "pkg.install",
    "pkg.remove",
    "pkg.search",
    "pkg.info",
    "pkg.cache.refresh",
    "pkg.upgrade",
    "svc.status",
    "svc.start",
    "svc.enable",
    "sys.info",
    "gui.launch",
    "file.append",
    UNKNOWN_LABEL,
]

_PACKAGES = [
    "htop",
    "curl",
    "vim",
    "git",
    "tmux",
    "jq",
    "tree",
    "wget",
    "ripgrep",
    "make",
    "openssl",
    "gzip",
    "bat",
    "fzf",
    "ncdu",
    "bmon",
    "strace",
    "lsof",
    "zip",
    "unrar",
]
_UNITS = [
    "nginx",
    "ssh",
    "docker",
    "cron",
    "bluetooth",
    "cups",
    "postgresql",
    "redis",
    "apache2",
    "tailscale",
    "ufw",
    "networkd",
]
_APPS = [
    "firefox",
    "code",
    "terminal",
    "files",
    "calculator",
    "gedit",
    "thunderbird",
    "vlc",
    "gimp",
    "chromium",
    "evolution",
    "nautilus",
]
_QUERIES = [
    "text editor",
    "web browser",
    "pdf reader",
    "music player",
    "terminal emulator",
    "markdown editor",
    "archive manager",
    "screenshot tool",
    "disk usage analyzer",
    "password manager",
    "video player",
    "note taking app",
]
_LINES = [
    "remember the milk",
    "deploy on friday",
    "server alpha details",
    "call the bank at 4",
    "rotate the logs weekly",
    "buy coffee beans",
]
_PATHS = [
    "~/notes.txt",
    "/tmp/TODO",
    "~/work/log.txt",
    "~/checklist.md",
    "~/ideas.txt",
]

_TEMPLATES: dict[str, list[str]] = {
    "pkg.install": [
        "install {p}",
        "install {p} and {q}",
        "please install {p}",
        "install the {p} package",
        "can you install {p}",
        "i need {p} installed",
        "add {p} to my machine",
        "get {p} on this box",
        "put {p} on my system",
        "set up {p} for me",
        "could you add the {p} package",
        "help me install {p}",
        "install both {p} and {q}",
        "i want {p} on here",
        "install {p} {q}",
        "get me {p}",
        "i need {p} on this machine",
        "need {p} on here",
        "i need the {p} package",
        "install {p} for me",
    ],
    "pkg.remove": [
        "remove {p}",
        "uninstall {p}",
        "please remove {p}",
        "get rid of {p}",
        "remove the {p} package",
        "delete {p} from my system",
        "i don't need {p} anymore",
        "uninstall {p} and {q}",
        "take {p} off this machine",
        "can you remove {p}",
        "remove {p} {q}",
        "uninstall the {p} package now",
    ],
    "pkg.search": [
        "search for a {query}",
        "search {query}",
        "find a {query}",
        "find me a {query}",
        "look for {query} packages",
        "search packages for a {query}",
        "is there a {query} available",
        "find {query}",
        "search for {query}",
        "any good {query} in the repos",
    ],
    "pkg.info": [
        "info {p}",
        "info about {p}",
        "details about {p}",
        "show {p}",
        "show info for {p}",
        "what is the {p} package",
        "tell me about the {p} package",
        "details for {p}",
        "show details about {p}",
        "info on the {p} package",
    ],
    "pkg.cache.refresh": [
        "update",
        "update the package cache",
        "update the package index",
        "refresh the package lists",
        "update package lists",
        "refresh repositories",
        "update the repos",
        "sync the package index",
        "update my package lists",
        "refresh the package index",
        "update the package lists now",
    ],
    "pkg.upgrade": [
        "upgrade the system",
        "upgrade my system",
        "update the whole system",
        "update everything",
        "upgrade all packages",
        "upgrade installed packages",
        "bring the system up to date",
        "full system upgrade",
        "update all",
        "do a system upgrade",
        "upgrade the whole machine",
        "update the system",
    ],
    "svc.status": [
        "status of {u}",
        "status of the {u} service",
        "is {u} running",
        "check {u} status",
        "show the status of {u}",
        "what's the status of {u}",
        "is the {u} service active",
        "state of the {u} unit",
        "is {u} active",
    ],
    "svc.start": [
        "start {u}",
        "start the {u} service",
        "start {u} now",
        "bring {u} up",
        "turn on the {u} service",
        "can you start {u}",
        "fire up {u}",
        "get {u} running",
        "start {u} service",
    ],
    "svc.enable": [
        "enable {u}",
        "enable the {u} service",
        "enable {u} at boot",
        "make {u} start on boot",
        "enable {u} on startup",
        "have {u} start automatically",
        "enable {u} to run at boot",
        "set {u} to start on boot",
    ],
    "sys.info": [
        "system info",
        "show system info",
        "system information",
        "what distro am i on",
        "give me system details",
        "hardware and os details",
        "about this machine",
        "machine fingerprint",
        "what hardware is this",
        "show os details",
        "system details please",
        "what os and hardware do i have",
        "system summary",
        "show machine info",
        "what distro is this",
        "machine info",
    ],
    "gui.launch": [
        "open {a}",
        "launch {a}",
        "run {a}",
        "start the {a} app",
        "open up {a}",
        "launch the {a} application",
        "can you open {a}",
        "fire up {a}",
        "open the {a} program",
        "run the {a} application for me",
    ],
    "file.append": [
        "append this line to {path}",
        "append {line} to {path}",
        "add the line {line} to {path}",
        "write {line} to the end of {path}",
        "append a line to {path}",
        "put {line} into {path}",
    ],
    UNKNOWN_LABEL: [
        "tell me a joke about {c}",
        "what's the weather in {c} tomorrow",
        "write me a poem about {a}",
        "order me a pizza",
        "play some jazz",
        "clean up my emails",
        "summarize this article about {t}",
        "translate hello to {lang}",
        "who won the match",
        "what is ostype",
        "explain systemd units to me",
        "how do i exit vim",
        "generate a password",
        "shutdown the machine",
        "reboot now",
        "set my volume to half",
        "change my wallpaper to {t}",
        "when is my next meeting",
        "book a flight to {c}",
        "remind me to call mom",
        "what's 2 plus 2",
        "draft an email to my boss",
        "fix my printer",
        "why is my computer slow",
        "backup my phone",
        "trim this video",
        "convert this pdf",
        "scrape that website",
        "train a model on my data",
        "scan that server for open ports",
        "delete my browsing history",
        "read me the news about {t}",
        "what time is it in {c}",
        "calculate my mortgage",
        "find my phone",
        "water the plants",
        "write a blog post about {t}",
    ],
}

_UNKNOWN_PREFIXES = ["", "please ", "can you ", "hey ", "i want you to ", "could you "]


_UNKNOWN_FILLERS = {
    "c": ["paris", "tokyo", "delhi", "london", "berlin", "lima"],
    "t": ["renewable energy", "ancient rome", "quantum computing", "street food", "jazz"],
    "lang": ["french", "japanese", "hindi", "swahili", "german"],
    "a2": ["cats", "mountains", "rain", "summer", "the sea"],
}


def _corpus(rng: random.Random) -> list[tuple[str, int]]:
    examples: list[tuple[str, int]] = []
    for label, templates in _TEMPLATES.items():
        texts: set[str] = set()
        guard = 0
        target = 1600 if label == UNKNOWN_LABEL else 520
        while len(texts) < target and guard < target * 50:
            guard += 1
            template = rng.choice(templates)
            fillers: dict[str, str] = {
                "p": rng.choice(_PACKAGES),
                "q": rng.choice(_PACKAGES),
                "u": rng.choice(_UNITS),
                "a": rng.choice(_APPS),
                "query": rng.choice(_QUERIES),
                "line": rng.choice(_LINES),
                "path": rng.choice(_PATHS),
            }
            if label == UNKNOWN_LABEL:
                fillers["a"] = rng.choice(_UNKNOWN_FILLERS["a2"])
                fillers["c"] = rng.choice(_UNKNOWN_FILLERS["c"])
                fillers["t"] = rng.choice(_UNKNOWN_FILLERS["t"])
                fillers["lang"] = rng.choice(_UNKNOWN_FILLERS["lang"])
            text = template.format(**fillers)
            if label == UNKNOWN_LABEL:
                text = rng.choice(_UNKNOWN_PREFIXES) + text
            texts.add(text)
        examples.extend((text, LABELS.index(label)) for text in texts)
    rng.shuffle(examples)
    return examples


def _forward(
    model: dict[str, object], buckets: dict[int, float]
) -> tuple[list[float], list[float]]:
    w1: list[list[float]] = model["w1"]  # type: ignore[assignment]
    b1: list[float] = model["b1"]  # type: ignore[assignment]
    w2: list[list[float]] = model["w2"]  # type: ignore[assignment]
    b2: list[float] = model["b2"]  # type: ignore[assignment]
    acc = list(b1)
    for index, value in buckets.items():
        row = w1[index]
        for j in range(HIDDEN):
            acc[j] += value * row[j]
    hidden = [value if value > 0.0 else 0.0 for value in acc]
    n_classes = len(b2)
    logits = [b2[k] + sum(hidden[j] * w2[j][k] for j in range(HIDDEN)) for k in range(n_classes)]
    peak = max(logits)
    exps = [math.exp(value - peak) for value in logits]
    total = sum(exps)
    return hidden, [value / total for value in exps]


def train(examples: list[tuple[str, int]]) -> dict[str, object]:
    rng = random.Random(SEED)
    # Random init breaks the ReLU symmetry: at W1=W2=0 every hidden unit is
    # dead (relu(0)=0), dh = W2*d2 = 0 forever, and only b2 would ever learn.
    model: dict[str, object] = {
        "w1": [[rng.uniform(-0.14, 0.14) for _ in range(HIDDEN)] for _ in range(FEATURE_DIM)],
        "b1": [0.0] * HIDDEN,
        "w2": [[rng.uniform(-0.2, 0.2) for _ in range(len(LABELS))] for _ in range(HIDDEN)],
        "b2": [0.0] * len(LABELS),
    }
    dataset = [(text, label, _features(text)) for text, label in examples]
    lr = LR
    for epoch in range(EPOCHS):
        order = list(range(len(dataset)))
        rng.shuffle(order)
        loss = 0.0
        w1: list[list[float]] = model["w1"]  # type: ignore[assignment]
        b1: list[float] = model["b1"]  # type: ignore[assignment]
        w2: list[list[float]] = model["w2"]  # type: ignore[assignment]
        b2: list[float] = model["b2"]  # type: ignore[assignment]
        for position in order:
            _text, label, buckets = dataset[position]
            hidden, probs = _forward(model, buckets)
            loss += -math.log(max(probs[label], 1e-12))
            d2 = [probs[k] - (1.0 if k == label else 0.0) for k in range(len(LABELS))]
            for k, grad in enumerate(d2):
                b2[k] -= lr * grad
            # Backprop through the ReLU with PRE-update w2, then update both
            # layers. dL/dW1[bucket][j] = x[bucket] * dh[j] for active j.
            for j in range(HIDDEN):
                if hidden[j] <= 0.0:
                    continue
                w2row = w2[j]
                back = 0.0
                for k in range(len(LABELS)):
                    back += w2row[k] * d2[k]
                step = lr * back
                b1[j] -= step
                for index, value in buckets.items():
                    w1[index][j] -= step * value
                for k in range(len(LABELS)):
                    w2row[k] -= lr * d2[k] * hidden[j]
        if epoch % 3 == 2:
            print(f"  epoch {epoch + 1}/{EPOCHS}  loss/example={loss / len(dataset):.4f}")
        lr *= LR_DECAY
    return model


def evaluate(model: dict[str, object], examples: list[tuple[str, int]]) -> dict[str, float]:
    correct_top1 = correct_top3 = 0
    for text, label in examples:
        probs = _forward(model, _features(text))[1]
        order = sorted(range(len(probs)), key=lambda k: probs[k], reverse=True)
        if order[0] == label:
            correct_top1 += 1
        if label in order[:3]:
            correct_top3 += 1
    n = max(len(examples), 1)
    return {"top1": correct_top1 / n, "top3": correct_top3 / n}


def unknown_recall(model: dict[str, object], ood: list[str]) -> float:
    """Abstention rate: argmax is unknown, OR no intent clears the threshold."""
    abstained = 0
    unknown_index = LABELS.index(UNKNOWN_LABEL)
    for text in ood:
        probs = _forward(model, _features(text))[1]
        order = sorted(range(len(probs)), key=lambda k: probs[k], reverse=True)
        if order[0] == unknown_index or probs[order[0]] < PROPOSE_THRESHOLD:
            abstained += 1
    return abstained / max(len(ood), 1)


def _stratified_holdout(
    examples: list[tuple[str, int]], rng: random.Random, fraction: float
) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    by_label: dict[int, list[tuple[str, int]]] = {}
    for pair in examples:
        by_label.setdefault(pair[1], []).append(pair)
    holdout: list[tuple[str, int]] = []
    train_set: list[tuple[str, int]] = []
    for _label, group in sorted(by_label.items()):
        rng.shuffle(group)
        cut = max(1, int(len(group) * fraction))
        holdout.extend(group[:cut])
        train_set.extend(group[cut:])
    rng.shuffle(train_set)
    return train_set, holdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="src/jarvis/intent/model.json")
    args = parser.parse_args()

    rng = random.Random(SEED)
    examples = _corpus(rng)
    train_set, holdout = _stratified_holdout(examples, rng, fraction=0.1)
    print(f"corpus: {len(examples)} examples ({len(train_set)} train / {len(holdout)} holdout)")

    model = train(train_set)

    # Gate the EXACT shipped artifact: round in place first (same rounding as
    # serialization), then evaluate — the gates describe model.json, not a
    # fuller-precision sibling of it.
    for matrix in ("w1", "w2"):
        model[matrix] = [
            [round(value, 5) for value in row]
            for row in model[matrix]  # type: ignore[arg-type,index-item]
        ]
    for vector in ("b1", "b2"):
        model[vector] = [round(value, 5) for value in model[vector]]  # type: ignore[arg-type,index-item]

    metrics = evaluate(model, holdout)
    ood_pool = [
        text
        for text, label in _corpus(random.Random(SEED + 1))
        if label == LABELS.index(UNKNOWN_LABEL)
    ]
    recall = unknown_recall(model, ood_pool)
    print(f"holdout: top1={metrics['top1']:.3f} top3={metrics['top3']:.3f}")
    print(f"ood abstention (unknown recall): {recall:.3f}")

    gates = metrics["top1"] >= 0.88 and metrics["top3"] >= 0.97 and recall >= 0.80
    if not gates:
        print("GATES FAILED — weights NOT written")
        return 1

    document = {
        "format": MODEL_FORMAT,
        "feature_dim": FEATURE_DIM,
        "hidden": HIDDEN,
        "seed": SEED,
        "labels": LABELS,
        "w1": model["w1"],  # type: ignore[dict-item]
        "b1": model["b1"],  # type: ignore[dict-item]
        "w2": model["w2"],  # type: ignore[dict-item]
        "b2": model["b2"],  # type: ignore[dict-item]
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(document, separators=(",", ":")), encoding="utf-8")
    size_kb = out_path.stat().st_size / 1024
    print(f"wrote {out_path} ({size_kb:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
