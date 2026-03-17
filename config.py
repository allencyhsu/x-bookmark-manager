"""Configuration loader — reads .env and exposes typed settings."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    # ── LLM ──────────────────────────────────────────
    llm_base_url: str = field(
        default_factory=lambda: os.getenv("LLM_BASE_URL", "http://ai-srv:8090/v1")
    )
    llm_api_key: str = field(
        default_factory=lambda: os.getenv("LLM_API_KEY", "not-needed")
    )
    llm_model: str = field(
        default_factory=lambda: os.getenv("LLM_MODEL", "qwen3.5")
    )

    # ── Database ─────────────────────────────────────
    database_path: str = field(
        default_factory=lambda: os.getenv("DATABASE_PATH", "bookmarks.db")
    )

    # ── Browser ──────────────────────────────────────
    browser_data_dir: Path = field(
        default_factory=lambda: Path(os.getenv("BROWSER_DATA_DIR", "browser_data"))
    )

    # ── Categories ───────────────────────────────────
    categories: list[str] = field(
        default_factory=lambda: [
            "Tech",
            "Design",
            "Business",
            "Life",
            "News",
            "Other",
        ]
    )


cfg = Config()
