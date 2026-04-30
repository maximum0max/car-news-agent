"""
Publish a post to WordPress via REST API. Handles tag find-or-create
so we can pass tag names rather than IDs.
"""
import json
import logging
import os
from typing import Any

import requests

from config import POST_STATUS, WP_CATEGORY_ID

log = logging.getLogger(__name__)


def publish_post(
    title: str,
    content: str,
    excerpt: str,
    slug: str,
    tags: list[str],
    featured_media: int | None = None,
) -> int:
    """Create a WordPress post and return its ID."""
    wp_url = os.environ["WP_URL"].rstrip("/")
    username = os.environ["WP_USERNAME"]
    password = os.environ["WP_APP_PASSWORD"]

    tag_ids = _resolve_tag_ids(wp_url, username, password, tags) if tags else []

    payload: dict[str, Any] = {
        "title": title,
        "content": content,
        "excerpt": excerpt,
        "slug": slug,
        "status": POST_STATUS,
        "tags": tag_ids,
    }
    if featured_media:
        payload["featured_media"] = featured_media
    if WP_CATEGORY_ID:
        payload["categories"] = [WP_CATEGORY_ID]

    posts_endpoint = f"{wp_url}/wp-json/wp/v2/posts"
    resp = requests.post(
        posts_endpoint,
        auth=(username, password),
        json=payload,
        timeout=30,
    )
    if not resp.ok:
        log.error(f"WP post creation failed: {resp.status_code} {resp.text[:500]}")
        resp.raise_for_status()

    post_id = _extract_post_id(resp.text)
    log.info(f"Created WP post id={post_id} status={POST_STATUS}")
    return post_id


def _extract_post_id(body: str) -> int:
    # A security plugin (Wordfence-style) may prepend a status object before
    # the real WP response, producing concatenated JSON like:
    #   {"status":0,"status_message":"ok","message_token":...}{"id":123,...}
    # Walk every top-level JSON object and return the first one with an "id".
    decoder = json.JSONDecoder()
    text = body.lstrip()
    while text:
        obj, end = decoder.raw_decode(text)
        if isinstance(obj, dict) and "id" in obj:
            return obj["id"]
        text = text[end:].lstrip()
    raise RuntimeError(f"No post object found in WP response: {body[:300]!r}")


def _resolve_tag_ids(
    wp_url: str,
    username: str,
    password: str,
    tag_names: list[str],
) -> list[int]:
    """For each tag name, find existing or create new, return list of IDs."""
    tags_endpoint = f"{wp_url}/wp-json/wp/v2/tags"
    auth = (username, password)
    ids: list[int] = []

    for name in tag_names:
        name = name.strip()
        if not name:
            continue
        try:
            # Search by exact name match.
            search = requests.get(
                tags_endpoint,
                auth=auth,
                params={"search": name, "per_page": 10},
                timeout=15,
            )
            search.raise_for_status()
            found = next(
                (t for t in search.json() if t.get("name", "").lower() == name.lower()),
                None,
            )
            if found:
                ids.append(found["id"])
                continue

            # Create it.
            create = requests.post(
                tags_endpoint,
                auth=auth,
                json={"name": name},
                timeout=15,
            )
            if create.ok:
                ids.append(create.json()["id"])
            else:
                log.warning(f"Could not create tag {name!r}: {create.status_code}")
        except requests.RequestException as e:
            log.warning(f"Tag resolution failed for {name!r}: {e}")
            continue

    return ids
