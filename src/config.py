"""
Configuration. Edit FEEDS to change sources, and the constants at the bottom
to tune behavior.
"""

# Two-tier feed strategy: PRIMARY (Ukrainian-language sources) is checked first.
# SECONDARY (English global sources) is only used when no new article is found
# in any primary feed — keeps the focus on Ukrainian-market content.
#
# When a secondary feed is used, the rewriter applies a Ukraine-relevance gate
# and skips articles with no realistic angle for Ukrainian readers (e.g. US-only
# municipal stories, e-bike/e-scooter promos, solar/wind tangents on electrek).
PRIMARY_FEEDS_UA = [
    "https://autogeek.com.ua/feed/",
    "https://news.infocar.ua/rss/news.php",
]

SECONDARY_FEEDS_EN = [
    "https://www.carscoops.com/feed/",
    "https://www.motor1.com/rss/articles/all/",
    "https://insideevs.com/rss/articles/all/",
    "https://electrek.co/feed/",
]

# Hostnames considered Ukrainian-language sources. Used by feeds.py to tag each
# candidate with `source_lang="uk"` so the rewriter knows not to translate.
UKRAINIAN_SOURCE_HOSTS = {
    "autogeek.com.ua",
    "news.infocar.ua",
    "infocar.ua",
}

# OpenAI model. gpt-4o has substantially better Ukrainian quality and
# follows length/structure constraints reliably — worth the ~10x cost
# vs gpt-4o-mini for content meant to rank in search.
OPENAI_MODEL = "gpt-4o"

# How many articles to look back per feed.
# We pick the newest unprocessed article across all feeds.
ITEMS_PER_FEED = 10

# Max posts to publish in a single workflow run.
# Keep this at 1 — the cron schedule controls daily volume by firing N times.
MAX_POSTS_PER_RUN = 1

# WordPress post status: "publish" goes live immediately, "draft" needs manual review.
# Set to "draft" for the first day to verify quality, then switch to "publish".
POST_STATUS = "publish"

# Optional: numeric category ID to assign posts to. Set to None to skip.
# Find category IDs in WP admin → Posts → Categories → hover a category, the
# URL contains ?taxonomy=category&tag_ID=N — that N is the ID.
WP_CATEGORY_ID = None

# Pexels search returns multiple images. We pick from the top N.
PEXELS_TOP_N = 5

# Article body fetch timeout (seconds). Some news sites are slow.
FETCH_TIMEOUT = 20

# Social channel URLs shown in the "Приєднуйтесь до наших каналів" CTA block
# at the bottom of every post. Set any *_URL to None to hide that channel.
SOCIAL_WHATSAPP_URL = "https://www.whatsapp.com/channel/0029VaWoeTALtOjLftmnSy2P"
SOCIAL_VIBER_URL = "https://invite.viber.com/?g2=AQAvsDVif3gD%2BVKav5sfNgo5pGirvnKfyu9t2W26wb0wJ7UwbDMq6lirja5lOaTK"
SOCIAL_TELEGRAM_URL = "https://t.me/newsauto_com_ua"

# Icon image URLs for the social buttons. Defaults to Simple Icons CDN, which
# serves clean white-on-transparent SVGs by brand name. To use a custom icon,
# upload it to WP media library and replace the URL with the hosted file.
SOCIAL_WHATSAPP_ICON = "https://cdn.simpleicons.org/whatsapp/white"
SOCIAL_VIBER_ICON = "https://cdn.simpleicons.org/viber/white"
SOCIAL_TELEGRAM_ICON = "https://cdn.simpleicons.org/telegram/white"

# How many "Читайте також" related posts to include at the end of each post.
# These are pulled from existing posts on the site that share tags with the
# new one, which is the strongest signal we have to keep them topically relevant.
RELATED_POSTS_COUNT = 3
