from __future__ import annotations

import asyncio
import logging

from app.config import get_env_settings, load_file_settings
from app.feishu import send_text_message
from app.news_agent import filter_news_by_llm, summarize_news
from app.news_fetcher import fetch_news

logger = logging.getLogger(__name__)


def _setup_logging() -> None:
    cfg = load_file_settings().get("logging", {})
    level_name = str(cfg.get("level", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)
    fmt = str(cfg.get("format", "%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=level, format=fmt)


def _validate_runtime_config() -> None:
    env = get_env_settings()
    cfg = load_file_settings()["feishu"]
    recipient_type = cfg.get("recipient_id_type", "chat_id")
    missing = []
    if not env.llm_api_key:
        missing.append("LLM_API_KEY")
    if not env.feishu_app_id:
        missing.append("FEISHU_APP_ID")
    if not env.feishu_app_secret:
        missing.append("FEISHU_APP_SECRET")
    if recipient_type == "open_id" and not env.feishu_open_id:
        missing.append("FEISHU_OPEN_ID")
    if recipient_type == "chat_id" and not env.feishu_chat_id:
        missing.append("FEISHU_CHAT_ID")
    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")


async def run_once() -> None:
    _setup_logging()
    logger.info("job_start")
    _validate_runtime_config()
    items = await fetch_news()
    logger.info("stage_fetch_done items=%s", len(items))
    filtered_items = await filter_news_by_llm(items)
    logger.info("stage_filter_done filtered_items=%s", len(filtered_items))
    digest = await summarize_news(filtered_items)
    logger.info("stage_summary_done digest_chars=%s", len(digest))
    await send_text_message(digest)
    logger.info("job_done")


def run() -> None:
    asyncio.run(run_once())


if __name__ == "__main__":
    run()
