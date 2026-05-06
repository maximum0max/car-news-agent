"""
Read RSS feeds, extract full article text, and manage the processed-URL state.
"""
import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import feedparser
import requests
import trafilatura

from config import FETCH_TIMEOUT, ITEMS_PER_FEED, UKRAINIAN_SOURCE_HOSTS

log = logging.getLogger(__name__)

STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "processed.json"

USER_AGENT = (
    "Mozilla/5.0 (compatible; CarNewsBot/1.0; +https://github.com/)"
)


def load_processed() -> set[str]:
    """Return the set of URLs already processed."""
    if not STATE_PATH.exists():
        return set()
    try:
        with STATE_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return set(data.get("processed", []))
    except (json.JSONDecodeError, OSError) as e:
        log.warning(f"Could not load state file: {e}. Starting fresh.")
        return set()


def mark_processed(url: str) -> None:
    """Add a URL to the processed list and write back."""
    processed = load_processed()
    processed.add(url)
    # Keep state file bounded — only retain the most recent 1000 entries.
    items = list(processed)[-1000:]
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with STATE_PATH.open("w", encoding="utf-8") as f:
        json.dump({"processed": items}, f, indent=2, ensure_ascii=False)


def fetch_article_text(url: str) -> str | None:
    """Fetch and extract the main article text from a URL."""
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=FETCH_TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        log.warning(f"Failed to fetch article body for {url}: {e}")
        return None

    text = trafilatura.extract(
        resp.text,
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )
    if not text or len(text) < 200:
        log.warning(f"Extracted text too short or empty for {url}")
        return None
    return text


def get_new_articles(
    primary_feeds: list[str],
    secondary_feeds: list[str],
    processed: set[str],
) -> list[dict[str, Any]]:
    """
    Two-tier article selection:
      1. Try primary (Ukrainian) feeds first — if any new article is found and
         its body extracts cleanly, return only those candidates.
      2. Only when primary feeds yield nothing usable, fall back to secondary
         (English) feeds. The rewriter then applies a Ukraine-relevance gate
         on these and may skip articles with no UA angle.

    Each returned candidate carries `source_lang` ("uk" or "en") so the
    rewriter can branch its prompt (translate vs. just restructure).
    """
    primary = _collect_candidates(primary_feeds, processed)
    enriched_primary = _enrich(primary)
    if enriched_primary:
        log.info(f"Using {len(enriched_primary)} primary (UA) candidate(s)")
        return enriched_primary

    log.info("No primary (UA) candidates available — falling back to secondary (EN) feeds")
    secondary = _collect_candidates(secondary_feeds, processed)
    enriched_secondary = _enrich(secondary)
    log.info(f"Found {len(enriched_secondary)} secondary (EN) candidate(s)")
    return enriched_secondary


def _collect_candidates(feeds: list[str], processed: set[str]) -> list[dict[str, Any]]:
    """Parse the given feeds and return un-processed entries sorted newest-first."""
    candidates: list[dict[str, Any]] = []

    for feed_url in feeds:
        log.info(f"Reading feed: {feed_url}")
        try:
            parsed = feedparser.parse(feed_url, request_headers={"User-Agent": USER_AGENT})
        except Exception as e:
            log.warning(f"Could not parse feed {feed_url}: {e}")
            continue

        for entry in parsed.entries[:ITEMS_PER_FEED]:
            link = entry.get("link", "").strip()
            if not link or link in processed:
                continue

            host = urlparse(link).netloc.lower().lstrip("www.")
            source_lang = "uk" if host in UKRAINIAN_SOURCE_HOSTS else "en"

            candidates.append({
                "url": link,
                "title": entry.get("title", "").strip(),
                "feed": feed_url,
                "source_lang": source_lang,
                "published": entry.get("published_parsed") or entry.get("updated_parsed"),
                "summary": entry.get("summary", ""),
            })

    candidates.sort(
        key=lambda x: x["published"] if x["published"] else (0,) * 9,
        reverse=True,
    )
    return candidates


def _enrich(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fetch full body text for the top candidates; drop any that fail."""
    enriched: list[dict[str, Any]] = []
    for cand in candidates[:5]:
        text = fetch_article_text(cand["url"])
        if not text:
            continue
        cand["content"] = text
        enriched.append(cand)
        if len(enriched) >= 3:
            break
    return enriched
