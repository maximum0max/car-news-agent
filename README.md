# Car News Auto-Poster

Automated pipeline that pulls car news from RSS feeds, rewrites it in Ukrainian using OpenAI, finds a matching photo on Pexels, and publishes it to your WordPress site. Runs on GitHub Actions (free) on a fixed schedule.

## What it does on each run

1. Fetches latest articles from the RSS feeds you've configured
2. Picks the first new (unprocessed) article
3. Fetches the full article text from the source URL
4. Sends it to OpenAI (`gpt-4o-mini`) which rewrites it in Ukrainian and returns structured JSON
5. Searches Pexels for a matching stock photo using English keywords from the rewrite
6. Uploads the photo to your WordPress media library and sets it as featured image
7. Publishes the post to WordPress with title, body, slug, excerpt, tags, and a "Джерело" link back to the original
8. Saves the original URL to `data/processed.json` and commits it back to the repo so the same article is never reposted

## Schedule

GitHub Actions cron fires 11 times per day in time windows roughly matching **8:00–12:00 and 18:00–21:00 Madrid time** (during summer time / CEST). Each fire processes at most one new article.

Cron times are in **UTC** because GitHub Actions doesn't support timezones. During winter (CET, last Sun of October to last Sun of March) shift the cron lines forward by 1 hour or just live with the 1-hour drift — it'll publish 7:00–11:00 / 17:00–20:00 local time in winter.

## Setup (one-time, ~20 minutes)

### 1. Create the GitHub repo

1. Create a new **private** GitHub repo
2. Push this entire folder to it
3. Don't put any keys in the code — they go in Secrets (next step)

### 2. Get your API keys ready

**OpenAI**
- Go to https://platform.openai.com/api-keys
- Create a new key, copy it
- Add billing — load $5–10, that lasts months at this volume

**Pexels**
- Go to https://www.pexels.com/api/
- Sign up, get your API key (free, 200 req/hour, 20k/month — way more than enough)

**WordPress Application Password**
- Log into your WP admin
- Go to **Users → Your Profile → Application Passwords** (scroll to bottom)
- Application name: `car-news-agent`
- Click **Add New Application Password**
- Copy the generated password (looks like `xxxx xxxx xxxx xxxx xxxx xxxx`) — keep the spaces, they're part of it
- Note your WP username (the one you log in with)

### 3. Add secrets to GitHub

In your repo: **Settings → Secrets and variables → Actions → New repository secret**. Add these five:

| Name | Value |
|---|---|
| `OPENAI_API_KEY` | `sk-...` from OpenAI |
| `PEXELS_API_KEY` | from Pexels dashboard |
| `WP_URL` | `https://yourdomain.com` (no trailing slash, no `/wp-admin`) |
| `WP_USERNAME` | your WordPress login username |
| `WP_APP_PASSWORD` | the application password from step 2 (with spaces) |

### 4. Configure your sources

Open `src/config.py` and edit the `FEEDS` list. The default has 4 good car news feeds. Add or remove as you like.

Also in `config.py`:
- `WP_CATEGORY_ID` — optional, set to your "News" category numeric ID, or leave as `None`
- `POST_STATUS` — `"publish"` (default, goes live immediately) or `"draft"` (recommended for the first day to spot-check output)

### 5. Test it once manually

In the repo, go to **Actions → Publish car news → Run workflow**. This triggers the workflow on demand without waiting for the schedule. Check the logs and your WP site.

If everything works, the schedule takes over automatically.

## Running locally (optional, for testing)

```bash
cd car-news-agent
pip install -r requirements.txt
cp .env.example .env
# fill in .env with your keys
python src/main.py
```

## Cost

| Item | Cost |
|---|---|
| GitHub Actions | Free (you'll use ~30 of 2,000 free minutes/month) |
| OpenAI gpt-4o-mini | ~$0.30/month at 360 posts |
| Pexels | Free |
| **Total** | **~$0.30/month** |

## Files

```
car-news-agent/
├── .github/workflows/publish.yml   # GitHub Actions schedule + run config
├── src/
│   ├── main.py                     # Orchestrator
│   ├── config.py                   # Feed list + settings
│   ├── feeds.py                    # RSS parsing + article extraction + dedup
│   ├── rewriter.py                 # OpenAI rewrite call
│   ├── images.py                   # Pexels search + WP upload
│   └── wordpress.py                # WP post creation + tag handling
├── data/processed.json             # State: list of URLs already posted
├── requirements.txt
├── .env.example                    # Template for local testing
└── README.md
```

## Troubleshooting

**Action runs but no post appears.** Check the run logs. Most common: WP_URL has trailing slash or includes `/wp-admin`. Should be `https://yourdomain.com` only.

**WP returns 401.** Application Password is wrong, or WP REST API is blocked. Some security plugins (Wordfence, iThemes) block REST API by default — whitelist `/wp-json/wp/v2/posts` and `/wp-json/wp/v2/media`.

**OpenAI returns invalid JSON.** Rare with `response_format=json_object`, but if it happens the script logs and skips that article. It'll try the next one on the next cron fire.

**No new articles.** Either the feeds aren't producing new content, or `data/processed.json` already contains them all. Look at the logs.

**Want to wipe state and start over.** Delete the contents of `data/processed.json` (replace with `{"processed": []}`) and commit.

## Changing the schedule

Edit `.github/workflows/publish.yml`. Cron format is `minute hour * * *` in UTC. https://crontab.guru helps. Each cron line = one workflow run.

To post more per day: add more cron lines. To post less: remove some.

## Changing the language

Default is Ukrainian. To switch, edit the `SYSTEM_PROMPT` constant at the top of `src/rewriter.py`.
