"""
Read RSS feeds, extract full article text, and manage the processed-URL state.
"""
import json
import logging
import random
from collections import defaultdict
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
    UA-first article selection with fair source rotation and a fallback to
    English feeds.

    Both tiers are collected up front, then ordered by this preference:
      1. Ukrainian sources NOT used recently  (randomized across feeds)
      2. English sources NOT used recently     (randomized across feeds)
      3. Ukrainian sources used recently        (least-recently-used first)
      4. English sources used recently          (least-recently-used first)

    The effect: we keep publishing Ukrainian content, but never repeat the
    same source while another UA feed has fresh material. Once every UA source
    has been used recently, we dip into the English feeds (the rewriter applies
    its Ukraine-relevance gate) instead of repeating a UA source — so coverage
    stays varied. Randomizing the order within each group means the run doesn't
    always lead with the same feed (e.g. autogeek).
    """
    ua = _collect_candidates(primary_feeds, processed)
    en = _collect_candidates(secondary_feeds, processed)
    ordered = _order_candidates(ua, en, recent_sources or [])

    if ordered:
        lead = ordered[0]
        log.info(
            f"{len(ua)} UA + {len(en)} EN candidate(s); "
            f"leading with [{lead['source_lang']}] {lead['source_host']}"
        )
    return _enrich(ordered)


def _collect_candidates(
    feeds: list[str],
    processed: set[str],
) -> list[dict[str, Any]]:
    """Parse the given feeds and return un-processed entries, newest first."""
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

    candidates.sort(key=lambda c: c["published"] or (0,) * 9, reverse=True)
    return candidates


def _shuffle_by_source(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Round-robin candidates across their source hosts in a random host order.
    Keeps each source's articles newest-first, but spreads different sources
    through the list so the top picks aren't all from one busy feed.
    """
    by_host: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in candidates:
        by_host[c["source_host"]].append(c)

    hosts = list(by_host.keys())
    random.shuffle(hosts)

    ordered: list[dict[str, Any]] = []
    while any(by_host[h] for h in hosts):
        for h in hosts:
            if by_host[h]:
                ordered.append(by_host[h].pop(0))
    return ordered


def _order_candidates(
    ua: list[dict[str, Any]],
    en: list[dict[str, Any]],
    recent_sources: list[str],
) -> list[dict[str, Any]]:
    """Apply the UA-first, rotate-then-dip-into-EN preference (see caller)."""
    recent_set = set(recent_sources)

    def split(cands: list[dict[str, Any]]):
        fresh = [c for c in cands if c["source_host"] not in recent_set]
        stale = [c for c in cands if c["source_host"] in recent_set]
        # Least-recently-used first: a host's recency is its index in the
        # most-recent-first `recent_sources` list (higher index = used longer ago).
        stale.sort(key=lambda c: recent_sources.index(c["source_host"]), reverse=True)
        return fresh, stale

    ua_fresh, ua_stale = split(ua)
    en_fresh, en_stale = split(en)

    return (
        _shuffle_by_source(ua_fresh)
        + _shuffle_by_source(en_fresh)
        + ua_stale
        + en_stale
    )


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
