from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import tomllib

BASE_DIR = Path(__file__).resolve().parent.parent
SETTINGS_FILE = BASE_DIR / "app" / "settings.toml"
ENV_FILE = BASE_DIR / ".env"


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    data: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        data[key.strip()] = value.strip()
    return data


@dataclass
class EnvSettings:
    llm_api_key: str = ""
    llm_model_name: str = ""
    llm_base_url: str = ""
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_chat_id: str = ""
    feishu_open_id: str = ""
    news_target_keywords: str = ""
    url_strip_param_prefixes: str = ""
    url_strip_param_exact: str = ""
    llm_retry_status_codes: str = ""
    filter_output_schema: str = ""
    filter_system_prompt: str = ""
    summary_grouping_rules: str = ""
    summary_output_template: str = ""


@lru_cache(maxsize=1)
def load_file_settings() -> dict[str, Any]:
    with SETTINGS_FILE.open("rb") as f:
        return tomllib.load(f)


@lru_cache(maxsize=1)
def get_env_settings() -> EnvSettings:
    file_env = _load_env_file(ENV_FILE)
    merged = {**file_env, **os.environ}
    return EnvSettings(
        llm_api_key=merged.get("LLM_API_KEY", ""),
        llm_model_name=merged.get("LLM_MODEL_NAME", ""),
        llm_base_url=merged.get("LLM_BASE_URL", ""),
        feishu_app_id=merged.get("FEISHU_APP_ID", ""),
        feishu_app_secret=merged.get("FEISHU_APP_SECRET", ""),
        feishu_chat_id=merged.get("FEISHU_CHAT_ID", ""),
        feishu_open_id=merged.get("FEISHU_OPEN_ID", ""),
        news_target_keywords=merged.get("NEWS_TARGET_KEYWORDS", ""),
        url_strip_param_prefixes=merged.get("URL_STRIP_PARAM_PREFIXES", ""),
        url_strip_param_exact=merged.get("URL_STRIP_PARAM_EXACT", ""),
        llm_retry_status_codes=merged.get("LLM_RETRY_STATUS_CODES", ""),
        filter_output_schema=merged.get("FILTER_OUTPUT_SCHEMA", ""),
        filter_system_prompt=merged.get("FILTER_SYSTEM_PROMPT", ""),
        summary_grouping_rules=merged.get("SUMMARY_GROUPING_RULES", ""),
        summary_output_template=merged.get("SUMMARY_OUTPUT_TEMPLATE", ""),
    )
