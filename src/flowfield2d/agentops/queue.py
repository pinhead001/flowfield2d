"""TOML task cards and a directory-backed queue.

A card targets exactly one repo. States are directories under the queue:
pending, running, done, escalated. Moving a file is the state change.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from filelock import FileLock

from flowfield2d.agentops.config import AgentOpsConfig

STATES = ("pending", "running", "done", "escalated")
REQUIRED = ("id", "repo", "title", "prompt", "acceptance")


class CardError(ValueError):
    pass


@dataclass
class Card:
    id: str
    repo: str
    title: str
    prompt: str
    acceptance: str
    base: str = "main"
    model: str | None = None
    print_timeout: str | None = None
    max_retries: int | None = None
    depends_on: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Card:
        missing = [k for k in REQUIRED if not str(d.get(k, "")).strip()]
        if missing:
            raise CardError(f"card missing fields: {', '.join(missing)}")
        cid = str(d["id"])
        if not all(c.isalnum() or c in "-_." for c in cid):
            raise CardError(f"card id must be [A-Za-z0-9._-]: {cid!r}")
        return cls(
            id=cid, repo=str(d["repo"]), title=str(d["title"]), prompt=str(d["prompt"]),
            acceptance=str(d["acceptance"]), base=str(d.get("base", "main")),
            model=d.get("model"), print_timeout=d.get("print_timeout"),
            max_retries=d.get("max_retries"), depends_on=list(d.get("depends_on", [])), raw=d,
        )

    @classmethod
    def load(cls, path: Path) -> Card:
        return cls.from_dict(tomllib.loads(path.read_text(encoding="utf-8")))


class Queue:
    def __init__(self, cfg: AgentOpsConfig) -> None:
        self.cfg = cfg
        self.root = cfg.queue_dir
        for s in STATES:
            (self.root / s).mkdir(parents=True, exist_ok=True)
        self._lock = FileLock(str(self.root / ".lock"))

    def add(self, path: Path) -> Card:
        card = Card.load(path)
        if card.repo not in self.cfg.repos:
            raise CardError(f"unknown repo {card.repo!r}; known: {sorted(self.cfg.repos)}")
        with self._lock:
            if self.state_of(card.id) is not None:
                raise CardError(f"card {card.id} already queued")
            (self.root / "pending" / f"{card.id}.toml").write_text(
                path.read_text(encoding="utf-8"), encoding="utf-8")
        return card

    def state_of(self, card_id: str) -> str | None:
        for s in STATES:
            if (self.root / s / f"{card_id}.toml").exists():
                return s
        return None

    def cards(self, state: str) -> list[Card]:
        return [Card.load(p) for p in sorted((self.root / state).glob("*.toml"))]

    def ready(self) -> list[Card]:
        done = {p.stem for p in (self.root / "done").glob("*.toml")}
        return [c for c in self.cards("pending") if set(c.depends_on) <= done]

    def claim_next(self) -> Card | None:
        with self._lock:
            ready = self.ready()
            if not ready:
                return None
            self._move(ready[0].id, "running")
            return ready[0]

    def move(self, card_id: str, state: str) -> None:
        with self._lock:
            self._move(card_id, state)

    def _move(self, card_id: str, state: str) -> None:
        if state not in STATES:
            raise CardError(f"bad state {state}")
        cur = self.state_of(card_id)
        if cur is None:
            raise CardError(f"card {card_id} not in queue")
        if cur != state:
            os.replace(self.root / cur / f"{card_id}.toml", self.root / state / f"{card_id}.toml")
