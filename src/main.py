"""
Main entry point. Run by GitHub Actions on a cron schedule, or locally for testing.
On each run: pick the newest unprocessed article, rewrite, find image, post to WP.
"""
import logging
import sys

from dotenv import load_dotenv

# Load .env for local runs. In GitHub Actions, env vars come from secrets.
load_dotenv()

from config import FEEDS, MAX_POSTS_PER_RUN
from feeds import get_new_articles, load_processed, mark_processed
from images import find_and_upload_image
from rewriter import escape_html, rewrite_article
from wordpress import publish_post

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

    candidates = get_new_articles(FEEDS, processed)
    if not candidates:
        log.info("No new articles to process. Exiting cleanly.")
        return 0

    posted = 0
    for article in candidates:
        if posted >= MAX_POSTS_PER_RUN:
            break

        url = article["url"]
        title = article["title"]
        log.info(f"Processing: {title}")
        log.info(f"  URL: {url}")

        try:
            rewritten = rewrite_article(
                title=title,
                content=article["content"],
                url=url,
            )
        except Exception as e:
            log.error(f"Rewrite failed: {e}", exc_info=True)
            # Mark as processed anyway so we don't keep retrying a bad article.
            mark_processed(url)
            continue

        try:
            media_id, photographer = find_and_upload_image(
                keywords=rewritten["image_keywords"],
                alt_text=rewritten.get("image_alt"),
            )
        except Exception as e:
            log.warning(f"Image step failed (continuing without): {e}")
            media_id, photographer = None, None

        body_html = _append_footer(
            rewritten["content_html"],
            photographer=photographer,
            source_url=rewritten["source_url"],
            source_title=rewritten["source_title"],
        )

        try:
            post_id = publish_post(
                title=rewritten["title"],
                content=body_html,
                excerpt=rewritten["excerpt"],
                slug=rewritten["slug"],
                tags=rewritten["tags"],
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


def _append_footer(
    content_html: str,
    photographer: str | None,
    source_url: str,
    source_title: str,
) -> str:
    parts = [content_html.rstrip()]
    if photographer:
        parts.append(f"<p><em>Фото: {escape_html(photographer)} / Pexels</em></p>")
    parts.append(
        f'<p><em>Джерело: '
        f'<a href="{source_url}" rel="nofollow noopener" target="_blank">{escape_html(source_title)}</a>'
        f'</em></p>'
    )
    return "\n".join(parts)


if __name__ == "__main__":
    sys.exit(run())
