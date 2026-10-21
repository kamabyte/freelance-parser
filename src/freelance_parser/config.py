from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

# repo root = .../freelance-parser  (this file is src/freelance_parser/config.py)
ROOT = Path(__file__).resolve().parents[2]


def _data_dir() -> Path:
    """Where the DB lives. In Docker it's a mounted volume (DATA_DIR=/data)."""
    return Path(os.getenv("DATA_DIR") or ROOT / "data")


def _override(data_dir: Path, name: str) -> Path:
    """A config.yaml / profile.md in the data dir wins over the one shipped in the repo,
    so a deployed bot can be tuned (and keep a private profile) without rebuilding."""
    local = data_dir / name
    return local if local.exists() else ROOT / name


@dataclass
class Config:
    # from config.yaml
    categories: list[int]
    poll_interval_seconds: int
    score_threshold: int
    budget_floor: int
    stack_primary: list[str]
    good_subcategories: list[str]
    negative_keywords: list[str]
    model: str

    # from .env
    telegram_token: str | None
    anthropic_api_key: str | None
    telegram_chat_id: str | None
    telegram_topic_id: int | None

    # paths
    db_path: Path
    profile_path: Path


def load_config(config_path: Path | None = None) -> Config:
    load_dotenv(ROOT / ".env")
    data_dir = _data_dir()
    config_path = config_path or _override(data_dir, "config.yaml")
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    stack = data.get("stack", {}) or {}

    topic_env = (os.getenv("TELEGRAM_TOPIC_ID") or "").strip()
    telegram_topic_id = int(topic_env) if topic_env.lstrip("-").isdigit() else None

    return Config(
        categories=[int(c) for c in data.get("categories", [5, 2])],
        poll_interval_seconds=int(data.get("poll_interval_seconds", 90)),
        score_threshold=int(data.get("score_threshold", 50)),
        budget_floor=int(data.get("budget_floor", 0)),
        stack_primary=[s.lower() for s in stack.get("primary", [])],
        good_subcategories=list(stack.get("good_subcategories", [])),
        negative_keywords=[s.lower() for s in data.get("negative_keywords", [])],
        model=str(data.get("model", "claude-opus-4-7")),
        telegram_token=os.getenv("TELEGRAM_BOT_TOKEN"),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        telegram_chat_id=(os.getenv("TELEGRAM_CHAT_ID") or "").strip() or None,
        telegram_topic_id=telegram_topic_id,
        db_path=data_dir / "parser.db",
        profile_path=_override(data_dir, "profile.md"),
    )
