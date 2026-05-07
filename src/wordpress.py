"""
Publish a post to WordPress via REST API. Handles tag find-or-create,
related-post lookup, and Wordfence-style concatenated-JSON responses.
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
    tag_ids: list[int],
    featured_media: int | None = None,
    focus_keyphrase: str | None = None,
    meta_description: str | None = None,
    seo_title: str | None = None,
) -> int:
    """Create a WordPress post and return its ID. Tags must already be resolved.

    `focus_keyphrase` / `meta_description` / `seo_title` are written as Yoast
    SEO post meta. Yoast doesn't expose these meta keys to REST by default —
    a small mu-plugin (yoast-rest-meta.php) must be installed on WP for the
    write to take effect. Without it, the meta keys are silently dropped and
    Yoast's SEO score stays red.
    """
    wp_url = os.environ["WP_URL"].rstrip("/")
    username = os.environ["WP_USERNAME"]
    password = os.environ["WP_APP_PASSWORD"]

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

    yoast_meta = {}
    if focus_keyphrase:
        yoast_meta["_yoast_wpseo_focuskw"] = focus_keyphrase
    if meta_description:
        yoast_meta["_yoast_wpseo_metadesc"] = meta_description
    if seo_title:
        yoast_meta["_yoast_wpseo_title"] = seo_title
    if yoast_meta:
        payload["meta"] = yoast_meta

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

    post_id = _extract_first_with_id(resp.text)["id"]
    log.info(f"Created WP post id={post_id} status={POST_STATUS}")
    return post_id


def resolve_tag_ids(tag_names: list[str]) -> list[int]:
    """For each tag name, find existing or create new, return list of IDs."""
    if not tag_names:
        return []
    wp_url = os.environ["WP_URL"].rstrip("/")
    auth = (os.environ["WP_USERNAME"], os.environ["WP_APP_PASSWORD"])
    tags_endpoint = f"{wp_url}/wp-json/wp/v2/tags"
    ids: list[int] = []

    for name in tag_names:
        name = name.strip()
        if not name:
            continue
        try:
            search = requests.get(
                tags_endpoint,
                auth=auth,
                params={"search": name, "per_page": 10},
                timeout=15,
            )
            search.raise_for_status()
            results = _extract_list(search.text)
            found = next(
                (t for t in results if t.get("name", "").lower() == name.lower()),
                None,
            )
            if found:
                ids.append(found["id"])
                continue

            create = requests.post(
                tags_endpoint,
                auth=auth,
                json={"name": name},
                timeout=15,
            )
            if create.ok:
                ids.append(_extract_first_with_id(create.text)["id"])
            else:
                log.warning(f"Could not create tag {name!r}: {create.status_code}")
        except (requests.RequestException, RuntimeError) as e:
            log.warning(f"Tag resolution failed for {name!r}: {e}")
            continue

    return ids


def find_related_posts(tag_ids: list[int], limit: int = 3) -> list[dict[str, Any]]:
    """
    Return up to `limit` recent posts that share at least one tag with the
    given tag_ids list. Each item is {"id", "link", "title"}.
    Returns [] if nothing matches or on any error — caller treats as optional.
    """
    if not tag_ids:
        return []
    wp_url = os.environ["WP_URL"].rstrip("/")
    auth = (os.environ["WP_USERNAME"], os.environ["WP_APP_PASSWORD"])
    posts_endpoint = f"{wp_url}/wp-json/wp/v2/posts"

    try:
        resp = requests.get(
            posts_endpoint,
            auth=auth,
            params={
                "tags": ",".join(str(t) for t in tag_ids),
                "per_page": limit,
                "_fields": "id,link,title",
                "status": "publish",
                "orderby": "date",
                "order": "desc",
            },
            timeout=15,
        )
        resp.raise_for_status()
        items = _extract_list(resp.text)
    except (requests.RequestException, RuntimeError) as e:
        log.warning(f"Related-posts lookup failed: {e}")
        return []

    out: list[dict[str, Any]] = []
    for it in items:
        title = it.get("title", {})
        rendered = title.get("rendered") if isinstance(title, dict) else None
        if not rendered or not it.get("link"):
            continue
        out.append({"id": it.get("id"), "link": it["link"], "title": rendered})
    return out


# ---- response parsing helpers ----------------------------------------------
# A security plugin (Wordfence-style) prepends a JSON status object before
# every response body, so plain resp.json() throws JSONDecodeError("Extra
# data"). These walk the concatenated JSON values and return the first one
# that looks like the data we want.

def _walk_json(body: str):
    decoder = json.JSONDecoder()
    text = body.lstrip()
    while text:
        obj, end = decoder.raw_decode(text)
        yield obj
        text = text[end:].lstrip()


def _extract_first_with_id(body: str) -> dict[str, Any]:
    for obj in _walk_json(body):
        if isinstance(obj, dict) and "id" in obj:
            return obj
    raise RuntimeError(f"No object with 'id' in WP response: {body[:300]!r}")


def _extract_list(body: str) -> list[dict[str, Any]]:
    for obj in _walk_json(body):
        if isinstance(obj, list):
            return obj
    return []
