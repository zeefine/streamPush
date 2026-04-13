from __future__ import annotations

import asyncio
import ast
import json
import logging
import random
import re
from dataclasses import dataclass

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage
from openai import APIConnectionError, APITimeoutError, RateLimitError

from app.config import get_env_settings, load_file_settings
from app.news_fetcher import NewsItem

logger = logging.getLogger(__name__)

DEFAULT_FILTER_SYSTEM_PROMPT = (
    "你是新闻分类助手。你需要根据标题和摘要判断新闻是否与目标关键词相关。"
    "请只返回 JSON，不要输出额外文本。"
)
DEFAULT_FILTER_OUTPUT_SCHEMA = (
    '{"results":[{"index":0,"is_related":true/false,"matched_keywords":["命中关键词"],"reason":"简短原因"}]}'
)
DEFAULT_SUMMARY_GROUPING_RULES = (
    "分组规则：\n"
    "1) 每条新闻只能放入一个最相关关键词分组。\n"
    "2) 如果同一条命中多个关键词，优先选择更具体的关键词（例如“石油”优先于“大宗商品”）。\n"
    "3) 若无合适分组，放入“其他相关”。"
)
DEFAULT_SUMMARY_OUTPUT_TEMPLATE = (
    "输出结构（严格遵守）：\n"
    "【今日要点】\n"
    "- 3到5条\n"
    "【按关键词分组】\n"
    "### 关键词A\n"
    "- 标题｜一句话总结｜链接\n"
    "### 关键词B\n"
    "- 标题｜一句话总结｜链接\n"
    "【团队建议】\n"
    "- 2到4条"
)


@dataclass
class ClassifiedNews:
    item: NewsItem
    matched_keywords: list[str]
    reason: str


def get_llm():
    env = get_env_settings()
    cfg = load_file_settings()["llm"]
    if not env.llm_api_key:
        raise ValueError("LLM_API_KEY is not set in environment variables")

    return init_chat_model(
        env.llm_model_name or cfg["model_name"],
        model_provider="openai",
        base_url=env.llm_base_url or cfg["base_url"],
        api_key=env.llm_api_key,
        temperature=cfg["temperature"],
        timeout=cfg["timeout_seconds"],
    )


def build_news_prompt(items: list[ClassifiedNews]) -> str:
    lines = []
    for idx, classified in enumerate(items, start=1):
        item = classified.item
        matched = "、".join(classified.matched_keywords) if classified.matched_keywords else "未标注"
        lines.append(
            f"{idx}. 标题: {item.title}\n"
            f"链接: {item.link}\n"
            f"来源: {item.source}\n"
            f"发布时间(UTC): {item.published_at.isoformat()}\n"
            f"命中关键词: {matched}\n"
            f"相关性说明: {classified.reason}\n"
            f"摘要: {item.summary[:500]}"
        )
    return "\n\n".join(lines)


def _normalize_multiline(text: str) -> str:
    return text.replace("\\n", "\n")


def _get_target_keywords(prompt_cfg: dict) -> list[str]:
    env = get_env_settings()
    raw_env_keywords = env.news_target_keywords.strip()
    if raw_env_keywords:
        env_keywords = [k.strip() for k in raw_env_keywords.split(",") if k.strip()]
        if env_keywords:
            return env_keywords

    keywords = prompt_cfg.get("target_keywords", [])
    if isinstance(keywords, list):
        cleaned = [str(k).strip() for k in keywords if str(k).strip()]
        if cleaned:
            return cleaned
    fallback = str(prompt_cfg.get("target_keyword", "")).strip()
    return [fallback] if fallback else []


def _get_filter_system_prompt(prompt_cfg: dict) -> str:
    env = get_env_settings()
    if env.filter_system_prompt.strip():
        return _normalize_multiline(env.filter_system_prompt.strip())
    raw = str(prompt_cfg.get("filter_system_prompt", "")).strip()
    if raw:
        return _normalize_multiline(raw)
    return DEFAULT_FILTER_SYSTEM_PROMPT


def _get_filter_output_schema(prompt_cfg: dict) -> str:
    env = get_env_settings()
    if env.filter_output_schema.strip():
        return _normalize_multiline(env.filter_output_schema.strip())
    raw = str(prompt_cfg.get("filter_output_schema", "")).strip()
    if raw:
        return _normalize_multiline(raw)
    return DEFAULT_FILTER_OUTPUT_SCHEMA


def _get_summary_grouping_rules(prompt_cfg: dict) -> str:
    env = get_env_settings()
    if env.summary_grouping_rules.strip():
        return _normalize_multiline(env.summary_grouping_rules.strip())
    raw = str(prompt_cfg.get("summary_grouping_rules", "")).strip()
    if raw:
        return _normalize_multiline(raw)
    return DEFAULT_SUMMARY_GROUPING_RULES


def _get_summary_output_template(prompt_cfg: dict) -> str:
    env = get_env_settings()
    if env.summary_output_template.strip():
        return _normalize_multiline(env.summary_output_template.strip())
    raw = str(prompt_cfg.get("summary_output_template", "")).strip()
    if raw:
        return _normalize_multiline(raw)
    return DEFAULT_SUMMARY_OUTPUT_TEMPLATE


def _try_parse_json(text: str) -> dict:
    try:
        return json.loads(text)
    except Exception:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except Exception:
        return {}


def _batched(seq: list[NewsItem], size: int) -> list[list[NewsItem]]:
    if size <= 0:
        size = len(seq) or 1
    return [seq[i : i + size] for i in range(0, len(seq), size)]


def _build_batch_filter_prompt(items: list[NewsItem]) -> str:
    parts: list[str] = []
    for idx, item in enumerate(items):
        parts.append(
            f"[{idx}]\n"
            f"标题: {item.title}\n"
            f"摘要: {item.summary[:1200]}"
        )
    return "\n\n".join(parts)


def _build_fallback_digest(items: list[ClassifiedNews], target_keyword_text: str) -> str:
    top_items = items[:8]
    highlight_lines = [f"- {classified.item.title}" for classified in top_items[:5]]
    news_lines = []
    for classified in top_items:
        item = classified.item
        matched = "、".join(classified.matched_keywords) if classified.matched_keywords else "未标注"
        news_lines.append(f"- {item.title}｜摘要生成超时，建议查看原文｜{matched}｜{item.link}")
    suggestion_lines = [
        "- 动作：优先阅读“今日要点”前3条原文；预期收益：快速掌握核心变化；优先级（高）",
        "- 动作：按关键词筛选关注标的并更新观察清单；预期收益：降低信息遗漏；优先级（中）",
    ]
    if not highlight_lines:
        highlight_lines = [f"- 今日未筛选到与“{target_keyword_text}”相关的新闻。"]
    return (
        "【今日要点】\n"
        + "\n".join(highlight_lines)
        + "\n【新闻速览】\n"
        + ("\n".join(news_lines) if news_lines else f"- 暂无相关新闻｜-｜-｜-")
        + "\n【团队建议】\n"
        + "\n".join(suggestion_lines)
    )


def _retry_config() -> tuple[int, float, float]:
    cfg = load_file_settings()["llm"]
    attempts = int(cfg.get("retry_max_attempts", 4))
    base_delay = float(cfg.get("retry_base_delay_seconds", 1.0))
    max_delay = float(cfg.get("retry_max_delay_seconds", 10.0))
    return max(1, attempts), max(0.0, base_delay), max(base_delay, max_delay)


def _retry_status_codes() -> set[int]:
    default = {429, 500, 502, 503, 504, 524}
    env = get_env_settings()
    raw = env.llm_retry_status_codes.strip()
    if not raw:
        return default
    parsed: set[int] = set()
    for token in raw.split(","):
        t = token.strip()
        if not t:
            continue
        try:
            parsed.add(int(t))
        except ValueError:
            continue
    return parsed or default


def _extract_provider_error_code(exc: Exception) -> int | None:
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code

    payload = exc.args[0] if exc.args else None
    if isinstance(payload, dict):
        code = payload.get("code")
        return code if isinstance(code, int) else None

    text = str(exc)
    if not text:
        return None
    for parser in (json.loads, ast.literal_eval):
        try:
            parsed = parser(text)
        except Exception:
            continue
        if isinstance(parsed, dict):
            code = parsed.get("code")
            if isinstance(code, int):
                return code
    return None


def _is_retriable_llm_error(exc: Exception) -> bool:
    if isinstance(exc, (RateLimitError, APITimeoutError, APIConnectionError)):
        return True
    code = _extract_provider_error_code(exc)
    if code in _retry_status_codes():
        return True
    # langchain_openai may wrap provider errors into ValueError(dict)
    return isinstance(exc, ValueError) and "provider returned error" in str(exc).lower()


def _extract_token_usage(resp) -> tuple[int, int, int]:
    usage = getattr(resp, "usage_metadata", None) or {}
    input_tokens = int(usage.get("input_tokens", 0) or 0)
    output_tokens = int(usage.get("output_tokens", 0) or 0)
    total_tokens = int(usage.get("total_tokens", 0) or 0)
    if total_tokens == 0:
        response_metadata = getattr(resp, "response_metadata", None) or {}
        token_usage = response_metadata.get("token_usage", {}) if isinstance(response_metadata, dict) else {}
        input_tokens = int(token_usage.get("prompt_tokens", input_tokens) or input_tokens)
        output_tokens = int(token_usage.get("completion_tokens", output_tokens) or output_tokens)
        total_tokens = int(token_usage.get("total_tokens", input_tokens + output_tokens) or input_tokens + output_tokens)
    return input_tokens, output_tokens, total_tokens


async def _ainvoke_with_retry(llm, messages, call_name: str = "unknown"):
    attempts, base_delay, max_delay = _retry_config()
    for i in range(attempts):
        try:
            if i > 0:
                logger.info("llm_retry_attempt attempt=%s/%s", i + 1, attempts)
            resp = await llm.ainvoke(messages)
            input_tokens, output_tokens, total_tokens = _extract_token_usage(resp)
            logger.info(
                "llm_token_usage call=%s input_tokens=%s output_tokens=%s total_tokens=%s",
                call_name,
                input_tokens,
                output_tokens,
                total_tokens,
            )
            return resp
        except Exception as exc:
            status_code = _extract_provider_error_code(exc)
            retriable = _is_retriable_llm_error(exc)
            if (not retriable) or i == attempts - 1:
                logger.error(
                    "llm_call_failed retriable=%s status_code=%s attempts=%s error=%s",
                    retriable,
                    status_code,
                    i + 1,
                    exc,
                )
                raise
            delay = min(max_delay, base_delay * (2**i))
            delay += random.uniform(0, max(0.0, delay * 0.2))
            logger.warning(
                "llm_call_retrying status_code=%s attempt=%s/%s sleep_seconds=%.2f error=%s",
                status_code,
                i + 1,
                attempts,
                delay,
                exc,
            )
            await asyncio.sleep(delay)


async def filter_news_by_llm(items: list[NewsItem]) -> list[ClassifiedNews]:
    if not items:
        return []

    cfg = load_file_settings()
    prompt_cfg = cfg["prompt"]
    target_keywords = _get_target_keywords(prompt_cfg)
    if not target_keywords:
        return [ClassifiedNews(item=item, matched_keywords=[], reason="未配置关键词，默认保留") for item in items]
    target_keyword_text = "、".join(target_keywords)
    filter_instruction = prompt_cfg["filter_instruction"]
    filter_system_prompt = _get_filter_system_prompt(prompt_cfg)
    filter_output_schema = _get_filter_output_schema(prompt_cfg)
    batch_size = int(prompt_cfg.get("filter_batch_size", 20))
    llm = get_llm()
    logger.info(
        "llm_filter_start items=%s batch_size=%s keyword_count=%s",
        len(items),
        batch_size,
        len(target_keywords),
    )

    selected: list[ClassifiedNews] = []
    for batch in _batched(items, batch_size):
        system_prompt = filter_system_prompt
        user_prompt = (
            f"目标关键词列表: {target_keyword_text}\n"
            f"判断规则: {filter_instruction}\n\n"
            "请对下面每条新闻做分类，返回 JSON 对象，格式如下：\n"
            f"{filter_output_schema}\n"
            "其中 index 对应新闻编号。\n\n"
            f"{_build_batch_filter_prompt(batch)}"
        )
        resp = await _ainvoke_with_retry(
            llm,
            [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
            call_name="filter",
        )

        text = (resp.content or "").strip()
        data = _try_parse_json(text)
        results = data.get("results", []) if isinstance(data, dict) else []
        if not isinstance(results, list):
            continue
        seen_indexes: set[int] = set()
        for result in results:
            if not isinstance(result, dict):
                continue
            idx = result.get("index")
            if not isinstance(idx, int) or idx < 0 or idx >= len(batch):
                continue
            if idx in seen_indexes:
                continue
            if not bool(result.get("is_related")):
                continue
            seen_indexes.add(idx)
            matched_keywords = result.get("matched_keywords", [])
            if not isinstance(matched_keywords, list):
                matched_keywords = []
            cleaned_keywords = [str(k).strip() for k in matched_keywords if str(k).strip()]
            cleaned_keywords = [k for k in cleaned_keywords if k in target_keywords]
            reason = str(result.get("reason", "")).strip()
            selected.append(
                ClassifiedNews(
                    item=batch[idx],
                    matched_keywords=cleaned_keywords,
                    reason=reason,
                )
            )
        logger.info("llm_filter_batch_done batch_items=%s selected_so_far=%s", len(batch), len(selected))
    logger.info("llm_filter_done selected=%s total=%s", len(selected), len(items))
    return selected


async def summarize_news(items: list[ClassifiedNews]) -> str:
    cfg = load_file_settings()
    prompt_cfg = cfg["prompt"]
    target_keywords = _get_target_keywords(prompt_cfg)
    summary_grouping_rules = _get_summary_grouping_rules(prompt_cfg)
    summary_output_template = _get_summary_output_template(prompt_cfg)
    target_keyword_text = "、".join(target_keywords) if target_keywords else "未配置"

    if not items:
        logger.info("llm_summary_skip_no_items")
        return f"今日未筛选到与关键词“{target_keyword_text}”相关的新闻。"

    llm = get_llm()
    system_prompt = f"{prompt_cfg['system_role']}\n{prompt_cfg['instruction']}"
    user_prompt = (
        f"目标关键词：{target_keyword_text}\n"
        "请根据以下新闻生成日报，并按“命中关键词”分组输出。\n"
        f"{summary_grouping_rules}\n\n"
        f"{summary_output_template}\n\n"
        "以下是新闻输入：\n"
        f"{build_news_prompt(items)}"
    )
    try:
        response = await _ainvoke_with_retry(
            llm,
            [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
            call_name="summary",
        )
    except Exception as exc:
        status_code = _extract_provider_error_code(exc)
        if status_code == 524:
            logger.error(
                "llm_summary_timeout_fallback status_code=%s input_items=%s",
                status_code,
                len(items),
            )
            return _build_fallback_digest(items, target_keyword_text)
        raise
    logger.info("llm_summary_done input_items=%s output_chars=%s", len(items), len(response.content or ""))
    return response.content
