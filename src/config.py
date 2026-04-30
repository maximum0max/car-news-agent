"""
Configuration. Edit FEEDS to change sources, and the constants at the bottom
to tune behavior.
"""

# RSS feeds to pull from. Verify each URL is alive before adding.
# Order doesn't matter — articles are picked by recency across all feeds.
FEEDS = [
    "https://www.carscoops.com/feed/",
    "https://www.motor1.com/rss/articles/all/",
    "https://insideevs.com/rss/articles/all/",
    "https://electrek.co/feed/",
]

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
