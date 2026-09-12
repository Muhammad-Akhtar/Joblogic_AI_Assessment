from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")


class Settings(BaseModel):
    ops_base_url: str = Field(default="http://127.0.0.1:8642")
    ops_api_key: str = Field(default="aerlink-ops-local-key")
    openai_api_key: str = Field(default="")
    openai_model: str = Field(default="gpt-4o")
    max_tool_rounds: int = Field(default=12)
    output_dir: Path = Field(default=_ROOT / "output")

    @classmethod
    def load(cls) -> "Settings":
        return cls(
            ops_base_url=os.environ.get("OPS_BASE_URL", "http://127.0.0.1:8642").rstrip("/"),
            ops_api_key=os.environ.get("OPS_API_KEY", "aerlink-ops-local-key"),
            openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
            openai_model=os.environ.get("OPENAI_MODEL", "gpt-4o"),
        )
