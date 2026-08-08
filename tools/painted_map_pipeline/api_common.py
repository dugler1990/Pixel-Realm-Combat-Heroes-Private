"""Shared helpers for the pipeline's thin, stdlib-only API clients.

Single home for logic that was copy-pasted across ``openai_api.py``,
``leonardo_api.py`` and ``collision/sam3/roboflow_workflow.py``. Each client keeps its
own error type and default env name by passing them in, so downstream ``except`` clauses
that catch a specific error type keep working.
"""

from __future__ import annotations

import os
from typing import Type


def api_key(config: dict, *, default_env: str, error_cls: Type[Exception]) -> str:
    """Return the API key from ``config['api_key_env']`` (or ``default_env``).

    Raises ``error_cls`` with the shared message if the variable is unset/empty.
    """
    env_name = str(config.get("api_key_env") or default_env)
    key = os.environ.get(env_name, "").strip()
    if not key:
        raise error_cls(f"Missing API key in environment variable {env_name!r}")
    return key
