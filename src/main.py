"""
Main entry point. Run by GitHub Actions on a cron schedule, or locally for testing.
On each run: pick the newest unprocessed article, rewrite, find image, post to WP.
"""
import json
import logging
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

# Load .env for local runs. In GitHub Actions, env vars come from secrets.
load_dotenv()

from config import (
    MAX_POSTS_PER_RUN,
    PRIMARY_FEEDS_UA,
    RELATED_POSTS_COUNT,
    SECONDARY_FEEDS_EN,
    SOCIAL_TELEGRAM_ICON,
    SOCIAL_TELEGRAM_URL,
    SOCIAL_VIBER_ICON,
    SOCIAL_VIBER_URL,
    SOCIAL_WHATSAPP_ICON,
    SOCIAL_WHATSAPP_URL,
)
from feeds import get_new_articles, load_processed, mark_processed
from images import find_and_upload_image
from rewriter import ArticleSkipped, escape_html, rewrite_article
from wordpress import find_related_posts, publish_post, resolve_tag_ids

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("car-news-agent")


def run() -> int:
    log.info("=" * 60)
    log.info("Car news agent starting")

    processed = load_processed()
    log.info(f"State: {len(processed)} articles previously processed")

    candidates = get_new_articles(PRIMARY_FEEDS_UA, SECONDARY_FEEDS_EN, processed)
    if not candidates:
        log.info("No new articles to process. Exiting cleanly.")
        return 0

    posted = 0
    for article in candidates:
        if posted >= MAX_POSTS_PER_RUN:
            break

        url = article["url"]
        title = article["title"]
        source_lang = article.get("source_lang", "en")
        log.info(f"Processing [{source_lang}]: {title}")
        log.info(f"  URL: {url}")

        try:
            rewritten = rewrite_article(
                title=title,
                content=article["content"],
                url=url,
                source_lang=source_lang,
            )
        except ArticleSkipped as e:
            log.info(f"Skipped (no UA relevance): {e}")
            # Mark processed so the same irrelevant article is never re-evaluated.
            mark_processed(url)
            continue
        except Exception as e:
            log.error(f"Rewrite failed: {e}", exc_info=True)
            # Mark as processed anyway so we don't keep retrying a bad article.
            mark_processed(url)
            continue

        try:
            media_id, photographer = find_and_upload_image(
                keywords=rewritten["image_keywords"],
                alt_text=rewritten.get("image_alt"),
                fallback_keywords=rewritten.get("image_keywords_fallback"),
            )
        except Exception as e:
            log.warning(f"Image step failed (continuing without): {e}")
            media_id, photographer = None, None

        tag_ids = resolve_tag_ids(rewritten["tags"])
        related = find_related_posts(tag_ids, limit=RELATED_POSTS_COUNT)
        log.info(f"Related posts found: {len(related)}")

        body_html = _build_full_body(
            rewritten,
            related=related,
            photographer=photographer,
        )

        try:
            post_id = publish_post(
                title=rewritten["title"],
                content=body_html,
                excerpt=rewritten.get("meta_description") or rewritten["excerpt"],
                slug=rewritten["slug"],
                tag_ids=tag_ids,
                featured_media=media_id,
            )
        except Exception as e:
            log.error(f"WP publish failed: {e}", exc_info=True)
            # Don't mark processed — we want to retry on next run.
            continue

        mark_processed(url)
        log.info(f"✓ Published post id={post_id}: {rewritten['title']}")
        posted += 1

    log.info(f"Run complete. Posted {posted} article(s).")
    return 0


def _build_full_body(
    rewritten: dict,
    related: list[dict],
    photographer: str | None,
) -> str:
    parts = [
        _jsonld_block(rewritten, photographer=photographer),
        rewritten["content_html"].rstrip(),
    ]
    faq = rewritten.get("faq") or []
    if faq:
        parts.append(_faq_block_html(faq))
    if related:
        parts.append(_related_block_html(related))
    parts.append(_social_block_html())
    if photographer:
        parts.append(f"<p><em>Фото: {escape_html(photographer)} / Pexels</em></p>")
    parts.append(
        f'<p><em>Джерело: '
        f'<a href="{rewritten["source_url"]}" rel="nofollow noopener" target="_blank">'
        f'{escape_html(rewritten["source_title"])}</a></em></p>'
    )
    return "\n".join(parts)


def _faq_block_html(faq: list[dict]) -> str:
    items = "".join(
        f'<details style="margin:8px 0;padding:12px 16px;background:#fff;'
        f'border:1px solid #e2e8f0;border-radius:6px;">'
        f'<summary style="font-weight:bold;cursor:pointer;font-size:16px;">'
        f'{escape_html(qa["q"])}</summary>'
        f'<p style="margin:10px 0 0 0;">{escape_html(qa["a"])}</p>'
        f'</details>'
        for qa in faq
    )
    return (
        '<div class="faq-block" style="margin:32px 0;padding:24px;'
        'background:#f8fafc;border-radius:8px;">'
        '<h2 style="margin:0 0 16px 0;">Часті запитання</h2>'
        f'{items}'
        '</div>'
    )


def _jsonld_block(rewritten: dict, photographer: str | None) -> str:
    """
    Inject JSON-LD structured data (Article + FAQPage). This is the single
    biggest SEO/GEO/AEO lever — it tells Google / Perplexity / ChatGPT Search
    exactly what the page is, what questions it answers, and who published it.
    """
    wp_url = os.environ.get("WP_URL", "").rstrip("/")
    site_host = wp_url or "https://newsauto.com.ua"
    canonical = f"{site_host}/novyny/{rewritten['slug']}/"
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    article_schema = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": rewritten["title"],
        "description": rewritten.get("meta_description") or rewritten["excerpt"],
        "datePublished": now_iso,
        "dateModified": now_iso,
        "inLanguage": "uk-UA",
        "mainEntityOfPage": {"@type": "WebPage", "@id": canonical},
        "author": {
            "@type": "Organization",
            "name": "Редакція newsauto.com.ua",
            "url": site_host,
        },
        "publisher": {
            "@type": "Organization",
            "name": "newsauto.com.ua",
            "url": site_host,
        },
        "keywords": ", ".join(rewritten.get("tags", [])),
    }
    if photographer:
        article_schema["image"] = {
            "@type": "ImageObject",
            "creditText": f"{photographer} / Pexels",
        }

    schemas = [article_schema]

    faq = rewritten.get("faq") or []
    if faq:
        schemas.append({
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": qa["q"],
                    "acceptedAnswer": {"@type": "Answer", "text": qa["a"]},
                }
                for qa in faq
            ],
        })

    blocks = "".join(
        f'<script type="application/ld+json">{json.dumps(s, ensure_ascii=False)}</script>'
        for s in schemas
    )
    return blocks


def _related_block_html(related: list[dict]) -> str:
    items = "".join(
        f'<li style="margin:8px 0;"><a href="{r["link"]}">{escape_html(r["title"])}</a></li>'
        for r in related
    )
    return (
        '<div class="related-posts" style="margin:30px 0;padding:20px 24px;'
        'background:#f5f7fa;border-left:4px solid #0066cc;border-radius:6px;">'
        '<h3 style="margin:0 0 12px 0;font-size:20px;">Читайте також</h3>'
        f'<ul style="list-style:disc;padding-left:20px;margin:0;">{items}</ul>'
        '</div>'
    )


def _social_block_html() -> str:
    channels = [
        (SOCIAL_WHATSAPP_URL, "#25D366", "WhatsApp", SOCIAL_WHATSAPP_ICON),
        (SOCIAL_VIBER_URL, "#7360F2", "Viber", SOCIAL_VIBER_ICON),
        (SOCIAL_TELEGRAM_URL, "#26A5E4", "Telegram", SOCIAL_TELEGRAM_ICON),
    ]
    button_style = (
        "display:inline-flex;align-items:center;justify-content:center;"
        "width:48px;height:48px;border-radius:50%;text-decoration:none;"
        "margin:0 6px;"
    )
    img_style = "width:26px;height:26px;display:block;"
    buttons = "".join(
        f'<a href="{url}" target="_blank" rel="noopener" aria-label="{name}" '
        f'style="{button_style}background:{color};">'
        f'<img src="{icon}" alt="{name}" width="26" height="26" style="{img_style}">'
        f'</a>'
        for url, color, name, icon in channels
        if url
    )
    return (
        '<div style="text-align:center;margin:32px 0;padding:24px 16px;'
        'background:#fafafa;border-radius:8px;">'
        '<p style="font-weight:bold;font-size:18px;margin:0 0 14px 0;">'
        'Приєднуйтесь до наших каналів</p>'
        f'<div style="display:flex;justify-content:center;align-items:center;">{buttons}</div>'
        '</div>'
    )


if __name__ == "__main__":
    sys.exit(run())
