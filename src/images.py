"""
Find a stock photo on Pexels matching the article and upload it to WordPress
as a media item. Returns the WP media ID for use as featured image.
"""
import logging
import os
import random
from io import BytesIO

import requests

from config import PEXELS_TOP_N

log = logging.getLogger(__name__)

PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"


def find_and_upload_image(
    keywords: str,
    alt_text: str | None = None,
    fallback_keywords: str | None = None,
) -> tuple[int | None, str | None]:
    """
    Search Pexels with the given keywords, download a top result,
    upload to WP media library, return (media_id, photographer_name).
    Either value can be None if a step fails — caller decides how to handle.
    `alt_text` is what gets stored on the WP media item (good for SEO);
    falls back to a generic Pexels credit if not provided.

    Tries `keywords` first, then `fallback_keywords` (typically just the brand
    name), then a generic "modern car" query — whichever returns a hit first
    wins. This avoids the "no photo at all" outcome when the rewriter picks
    a search query Pexels has nothing for (rare/new model names).
    """
    queries = [q.strip() for q in [keywords, fallback_keywords, "modern car"] if q and q.strip()]

    photo_url, photographer, matched_query = None, None, None
    for query in queries:
        photo_url, photographer = _search_pexels(query)
        if photo_url:
            matched_query = query
            log.info(f"Pexels matched on query: {query!r}")
            break
        log.info(f"Pexels: no result for {query!r}, trying next")

    if not photo_url:
        log.warning(f"No Pexels result for any query in {queries}")
        return None, None

    image_bytes, content_type = _download_image(photo_url)
    if not image_bytes:
        return None, photographer

    filename = _safe_filename(matched_query or keywords) + ".jpg"
    final_alt = alt_text or (
        f"Photo by {photographer} on Pexels" if photographer else (matched_query or keywords)
    )

    media_id = _upload_to_wp(image_bytes, content_type, filename, final_alt)
    return media_id, photographer


def _search_pexels(query: str) -> tuple[str | None, str | None]:
    """Search Pexels and return (photo_url, photographer_name) for a top result."""
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key:
        log.warning("PEXELS_API_KEY not set — skipping image")
        return None, None

    try:
        resp = requests.get(
            PEXELS_SEARCH_URL,
            headers={"Authorization": api_key},
            params={"query": query, "per_page": PEXELS_TOP_N, "orientation": "landscape"},
            timeout=15,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        log.warning(f"Pexels API error: {e}")
        return None, None

    photos = resp.json().get("photos", [])
    if not photos:
        return None, None

    chosen = random.choice(photos)
    # Use 'large' size — good quality, reasonable filesize.
    photo_url = chosen.get("src", {}).get("large") or chosen.get("src", {}).get("original")
    photographer = chosen.get("photographer")
    return photo_url, photographer


def _download_image(url: str) -> tuple[bytes | None, str]:
    """Download image bytes from URL."""
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        ct = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
        return resp.content, ct
    except requests.RequestException as e:
        log.warning(f"Image download failed: {e}")
        return None, ""


def _safe_filename(text: str) -> str:
    """Convert keywords to a safe filename stem."""
    safe = "".join(c if c.isalnum() else "-" for c in text.lower())
    safe = "-".join(filter(None, safe.split("-")))
    return safe[:50] or "image"


def _upload_to_wp(
    image_bytes: bytes,
    content_type: str,
    filename: str,
    alt_text: str,
) -> int | None:
    """Upload an image to WordPress media library, return media ID."""
    wp_url = os.environ["WP_URL"].rstrip("/")
    username = os.environ["WP_USERNAME"]
    password = os.environ["WP_APP_PASSWORD"]

    media_endpoint = f"{wp_url}/wp-json/wp/v2/media"

    try:
        resp = requests.post(
            media_endpoint,
            auth=(username, password),
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Type": content_type,
            },
            data=image_bytes,
            timeout=60,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        log.warning(f"WP media upload failed: {e}")
        if hasattr(e, "response") and e.response is not None:
            log.warning(f"WP response: {e.response.status_code} {e.response.text[:300]}")
        return None

    data = resp.json()
    media_id = data.get("id")

    # Set alt text on the media item.
    if media_id and alt_text:
        try:
            requests.post(
                f"{media_endpoint}/{media_id}",
                auth=(username, password),
                json={"alt_text": alt_text},
                timeout=15,
            )
        except requests.RequestException:
            pass  # Non-fatal — image is already uploaded.

    log.info(f"Uploaded image to WP, media_id={media_id}")
    return media_id
