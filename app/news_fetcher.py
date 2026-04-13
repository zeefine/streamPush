from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from xml.etree import ElementTree as ET

import httpx

from app.config import load_file_settings
from app.config import get_env_settings

logger = logging.getLogger(__name__)

TRACKING_PARAM_PREFIXES = ("utm_",)
TRACKING_PARAM_EXACT = {
    "spm",
    "from",
    "source",
    "ref",
    "ref_src",
    "ref_url",
    "fbclid",
    "gclid",
    "igshid",
    "mkt_tok",
    "_hsenc",
    "_hsmi",
}


def _normalized_param_rules() -> tuple[tuple[str, ...], set[str]]:
    env = get_env_settings()
    prefixes = TRACKING_PARAM_PREFIXES
    exact = set(TRACKING_PARAM_EXACT)

    if env.url_strip_param_prefixes.strip():
        parsed_prefixes = tuple(
            p.strip().lower()
            for p in env.url_strip_param_prefixes.split(",")
            if p.strip()
        )
        if parsed_prefixes:
            prefixes = parsed_prefixes
    if env.url_strip_param_exact.strip():
        parsed_exact = {
            p.strip().lower()
            for p in env.url_strip_param_exact.split(",")
            if p.strip()
        }
        if parsed_exact:
            exact = parsed_exact
    return prefixes, exact


@dataclass
class NewsItem:
    title: str
    link: str
    source: str
    published_at: datetime
    summary: str


def _strip(tag: str) -> str:
    return tag.split("}", 1)[-1]


def _parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
        return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
    except Exception:
        return None


def normalize_url(url: str) -> str:
    """Normalize URL for stable deduplication across tracking variants."""
    if not url:
        return ""
    try:
        parsed = urlsplit(url.strip())
    except Exception:
        return url

    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    port = parsed.port
    if not hostname:
        return url

    netloc = hostname
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{hostname}:{port}"

    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"

    prefixes, exact = _normalized_param_rules()
    cleaned_params = []
    for k, v in parse_qsl(parsed.query, keep_blank_values=True):
        key = k.lower()
        if key.startswith(prefixes) or key in exact:
            continue
        cleaned_params.append((k, v))
    cleaned_params.sort(key=lambda x: (x[0].lower(), x[1]))
    query = urlencode(cleaned_params, doseq=True)

    # Drop fragment to avoid duplicate URLs from anchors.
    return urlunsplit((scheme, netloc, path, query, ""))


def _parse_rss(root: ET.Element, source: str) -> list[NewsItem]:
    items: list[NewsItem] = []
    for node in root.findall(".//item"):
        title = (node.findtext("title") or "").strip()
        link = (node.findtext("link") or "").strip()
        summary = (node.findtext("description") or "").strip()
        dt = _parse_dt((node.findtext("pubDate") or "").strip()) or datetime.now(UTC)
        if title and link:
            items.append(NewsItem(title=title, link=link, source=source, published_at=dt, summary=summary))
    return items


def _parse_atom(root: ET.Element, source: str) -> list[NewsItem]:
    items: list[NewsItem] = []
    for entry in root.findall(".//{*}entry"):
        title = (entry.findtext("{*}title") or "").strip()
        summary = (entry.findtext("{*}summary") or "").strip()
        link = ""
        for link_node in entry.findall("{*}link"):
            href = (link_node.attrib.get("href") or "").strip()
            if href:
                link = href
                break
        dt_text = (entry.findtext("{*}updated") or entry.findtext("{*}published") or "").strip()
        dt = _parse_dt(dt_text) or datetime.now(UTC)
        if title and link:
            items.append(NewsItem(title=title, link=link, source=source, published_at=dt, summary=summary))
    return items


def _parse_feed(xml_text: str, source: str) -> list[NewsItem]:
    root = ET.fromstring(xml_text)
    tag = _strip(root.tag).lower()
    if tag == "rss":
        return _parse_rss(root, source)
    if tag == "feed":
        return _parse_atom(root, source)
    return []


def _filter_items(items: Iterable[NewsItem]) -> list[NewsItem]:
    cfg = load_file_settings()["news"]
    lookback_hours = int(cfg.get("lookback_hours", 24))
    max_items = int(cfg.get("max_items", 8))
    cutoff = datetime.now(UTC) - timedelta(hours=lookback_hours)

    unique_links: set[str] = set()
    selected: list[NewsItem] = []
    for item in sorted(items, key=lambda x: x.published_at, reverse=True):
        canonical_link = normalize_url(item.link)
        if canonical_link in unique_links:
            continue
        if item.published_at < cutoff:
            continue
        unique_links.add(canonical_link)
        selected.append(item)
        if len(selected) >= max_items:
            break
    return selected


async def fetch_news() -> list[NewsItem]:
    cfg = load_file_settings()["news"]
    rss_urls: list[str] = cfg.get("rss_urls", [])
    if not rss_urls:
        return []

    all_items: list[NewsItem] = []
    failed_sources = 0
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        for url in rss_urls:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                parsed = _parse_feed(resp.text, source=url)
                all_items.extend(parsed)
                logger.info("news_source_fetched source=%s items=%s", url, len(parsed))
            except Exception as exc:
                failed_sources += 1
                logger.warning("news_source_failed source=%s error=%s", url, exc)
                continue
    filtered = _filter_items(all_items)
    logger.info(
        "news_fetch_summary total_raw=%s total_filtered=%s source_count=%s failed_sources=%s",
        len(all_items),
        len(filtered),
        len(rss_urls),
        failed_sources,
    )
    return filtered
