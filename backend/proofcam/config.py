"""Runtime configuration. Secrets come only from the environment / .env."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]


class MissingCredentialsError(RuntimeError):
    pass


def database_path() -> Path:
    """SQLite file for inspections: PROOFCAM_DB_PATH (relative paths are relative to the repo root),
    default var/proofcam.db. Git-ignored; holds private photos."""
    load_dotenv(REPO_ROOT / ".env")
    p = Path(os.environ.get("PROOFCAM_DB_PATH", "").strip() or "var/proofcam.db")
    return p if p.is_absolute() else REPO_ROOT / p


@dataclass(frozen=True)
class Budget:
    """Hard limits on a single inspection. All loops must respect these."""

    max_observations: int = 6
    max_model_calls: int = 40
    max_attempts_per_gap: int = 2
    max_sam_calls_per_image: int = 4


@dataclass(frozen=True)
class Settings:
    api_key: str
    api_base: str = "https://api.meta.ai/v1"
    muse_model: str = "muse-spark-1.3"
    sam_model: str = "sam-3.1"
    # Chat Completions top-level `reasoning_effort` (minimal|low|medium|high|xhigh|max; "none" -> 400 on Spark).
    # None = omit the parameter and use the API default.
    muse_reasoning_effort: str | None = None
    muse_timeout_s: float = 120.0
    sam_timeout_s: float = 90.0
    max_retries: int = 2
    max_retry_wait_s: float = 30.0
    # Long side, in pixels, of the normalized image sent to BOTH Muse and SAM.
    # One shared image keeps Muse's 0-1000 grid and SAM's pixel boxes in one basis.
    image_max_side: int = 1600
    budget: Budget = field(default_factory=Budget)

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv(REPO_ROOT / ".env")
        key = os.environ.get("MODEL_API_KEY", "").strip()
        if not key:
            raise MissingCredentialsError(
                "MODEL_API_KEY is not set. Copy .env.example to .env at the repo root "
                "and add your Meta Model API key (https://dev.meta.ai)."
            )
        return cls(
            api_key=key,
            api_base=os.environ.get("PROOFCAM_API_BASE", cls.api_base),
            muse_model=os.environ.get("PROOFCAM_MUSE_MODEL", cls.muse_model),
            sam_model=os.environ.get("PROOFCAM_SAM_MODEL", cls.sam_model),
            muse_reasoning_effort=os.environ.get("PROOFCAM_MUSE_REASONING_EFFORT") or None,
        )
