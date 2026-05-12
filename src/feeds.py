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

from config import FETCH_TIMEOUT, ITEMS_PER_FEED, RECENT_SOURCES_LIMIT, UKRAINIAN_SOURCE_HOSTS

log = logging.getLogger(__name__)

STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "processed.json"

USER_AGENT = (
    "Mozilla/5.0 (compatible; CarNewsBot/1.0; +https://github.com/)"
)


def _load_state() -> dict[str, Any]:
    """Load the full state dict from disk. Returns {} on missing/corrupt file."""
    if not STATE_PATH.exists():
        return {}
    try:
        with STATE_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log.warning(f"Could not load state file: {e}. Starting fresh.")
        return {}


def load_processed() -> set[str]:
    """Return the set of URLs already processed."""
    return set(_load_state().get("processed", []))


def load_recent_sources() -> list[str]:
    """Return list of recently-published source hostnames, most-recent first."""
    return list(_load_state().get("recent_sources", []))


def mark_processed(url: str, source_host: str | None = None) -> None:
    """
    Mark `url` as processed. If `source_host` is given, also push it onto
    the recent-sources rotation list (most-recent first, bounded length).
    """
    state = _load_state()
    processed = set(state.get("processed", []))
    processed.add(url)
    # Keep state file bounded — only retain the most recent 1000 entries.
    items = list(processed)[-1000:]

    recent = list(state.get("recent_sources", []))
    if source_host:
        # Move host to front, dedupe, truncate.
        recent = [source_host] + [h for h in recent if h != source_host]
        recent = recent[:RECENT_SOURCES_LIMIT]

    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with STATE_PATH.open("w", encoding="utf-8") as f:
        json.dump(
            {"processed": items, "recent_sources": recent},
            f, indent=2, ensure_ascii=False,
        )


def _parse_host(url: str) -> str:
    """Extract a normalized hostname (lowercase, no leading 'www.')."""
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


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
    recent_sources: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Two-tier article selection with source rotation:
      1. Try primary (Ukrainian) feeds first — if any new article is found and
         its body extracts cleanly, return only those candidates.
      2. Only when primary feeds yield nothing usable, fall back to secondary
         (English) feeds. The rewriter applies a Ukraine-relevance gate.

    Within each tier, candidates whose host is NOT in `recent_sources` are
    preferred — this is how we stop one busy feed from monopolizing the queue.
    """
    primary = _collect_candidates(primary_feeds, processed, recent_sources)
    enriched_primary = _enrich(primary)
    if enriched_primary:
        log.info(f"Using {len(enriched_primary)} primary (UA) candidate(s)")
        return enriched_primary

    log.info("No primary (UA) candidates available — falling back to secondary (EN) feeds")
    secondary = _collect_candidates(secondary_feeds, processed, recent_sources)
    enriched_secondary = _enrich(secondary)
    log.info(f"Found {len(enriched_secondary)} secondary (EN) candidate(s)")
    return enriched_secondary


def _collect_candidates(
    feeds: list[str],
    processed: set[str],
    recent_sources: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Parse the given feeds and return un-processed entries. Ordering:
    candidates whose host is NOT in `recent_sources` come first (newest-first
    inside that group), then candidates from recent hosts (also newest-first).
    """
    recent_set = set(recent_sources or [])
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

            host = _parse_host(link)
            source_lang = "uk" if host in UKRAINIAN_SOURCE_HOSTS else "en"

            candidates.append({
                "url": link,
                "title": entry.get("title", "").strip(),
                "feed": feed_url,
                "source_host": host,
                "source_lang": source_lang,
                "published": entry.get("published_parsed") or entry.get("updated_parsed"),
                "summary": entry.get("summary", ""),
            })

    # Two stable sorts. First by date desc (newest first), then by
    # was-this-host-used-recently (False=0 before True=1). The stable sort
    # preserves the date order within each rotation group.
    candidates.sort(key=lambda c: c["published"] or (0,) * 9, reverse=True)
    candidates.sort(key=lambda c: c["source_host"] in recent_set)
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
