"""
Send an English car news article to OpenAI and get back a Ukrainian rewrite
in structured JSON format ready for WordPress.
"""
import json
import logging
import os
from typing import Any

from openai import OpenAI
from slugify import slugify

from config import OPENAI_MODEL

log = logging.getLogger(__name__)


SYSTEM_PROMPT = """Ти — досвідчений український автомобільний журналіст і SEO-копірайтер. Твоя задача — створити українську SEO-оптимізовану статтю на основі англомовного джерела для авто-новинного сайту newsauto.com.ua.

КЛЮЧОВЕ СЛОВО (focus keyword):
Перш ніж писати, обери ОДНЕ основне ключове слово українською мовою (1–3 слова), що точно відображає головну тему статті. Приклади: "Tesla Semi", "електропікап Rivian", "оновлення BMW M3", "відгук Hyundai Ioniq 5".
Це ключове слово ОБОВ'ЯЗКОВО використовуй:
- У заголовку (бажано в перших 30 символах).
- У першому реченні вступного абзацу.
- Принаймні в одному <h2>.
- У тексті статті 3–5 разів природно (без переспаму).
- В excerpt.
- В image_alt.
Поряд з основним ключем використовуй синоніми та LSI-варіанти ("електромобіль" / "EV" / "електрокар"), щоб текст звучав природно.

SEO-ВИМОГИ:
1. title: 50–65 символів. Ключове слово ближче до початку. Без CAPS LOCK і клікбейту. Можна використати число або рік для CTR.
2. excerpt: 140–160 символів — це буде meta description. Стисла суть + ключове слово + причина клікнути. Закінчуй крапкою. ЦІЛЬ — не менше 140 і не більше 160 символів.
3. content_html: 500–700 слів якісного унікального тексту. Це КРИТИЧНО: тіло статті має бути у цьому діапазоні. Перевір кількість слів перш ніж віддавати JSON.
4. Якщо у джерелі мало деталей — НЕ вигадуй цифр, цін чи цитат. Натомість додай контекст: коротка історія моделі/виробника, ситуація на ринку EV/авто, порівняння з конкурентами як ЗАГАЛЬНУ галузеву інформацію (без конкретних цифр, яких немає в джерелі). Поясни ширше, чому ця новина має значення для українських водіїв та покупців.
5. НІКОЛИ не вигадуй конкретні характеристики, ціни, цитати або дати, яких немає в джерелі. Загальні фрази на кшталт "сучасні електромобілі зазвичай мають запас ходу до 500 км" — допустимі лише як загальновідомий контекст, не як факт про конкретну модель.

ВИМОГИ ДО ЧИТАБЕЛЬНОСТІ:
1. Природна, жива українська мова, журналістський тон.
2. Короткі абзаци (2–4 речення).
3. Короткі речення, активний голос. Уникай канцеляриту і пасивних конструкцій.
4. Звертайся до читача "ви" там, де доречно.
5. Конкретика замість загальних фраз: цифри, моделі, дати з джерела.

ОБОВ'ЯЗКОВА СТРУКТУРА content_html (саме у такому порядку, з рекомендованою кількістю слів для досягнення 500–700 слів загалом):
1. <p> — вступний абзац без заголовка, 3–5 речень (~70–100 слів). У ПЕРШОМУ реченні згадай основне ключове слово і поясни актуальність новини.
2. <h2> — тематичний підзаголовок з ключовим словом або синонімом (наприклад: «Що відомо про оновлення Tesla Semi», «Ключові зміни нового BMW M3»). Далі 3 абзаци <p> по 4–6 речень (~70–100 слів кожен): перший абзац — основні факти з джерела, другий абзац — контекст про модель/бренд/ринок, третій абзац — порівняння з аналогами або історичний фон.
3. <h2> — практичний підзаголовок (наприклад: «Що це означає для покупців», «На що звернути увагу водіям», «Практичні наслідки для власників»). Далі <ul> з 5 пунктами <li>. Кожен <li> ПОЧИНАЄТЬСЯ з виділеної фрази у <strong>, потім двокрапка і РОЗГОРНУТЕ пояснення на 2–3 речення (~25–40 слів на пункт).
4. <h2>Висновок</h2> і підсумковий абзац <p> на 3–4 речення (~50–70 слів), який резюмує головну думку і повторює ключове слово в останньому або передостанньому реченні.

Сумарно цільова довжина — 500–700 слів. Якщо насумувалось менше 500 — розгорни абзаци контексту (пункт 2) і пункти списку (пункт 3) деталями про бренд, історію моделі, ринкову ситуацію, не вигадуючи цифр.

НЕ додавай у content_html: посилання на джерело, кредит фото, згадки автора оригіналу, фрази "Читайте також" — все це додається автоматично після твого тексту.

ДОДАТКОВІ ПОЛЯ:
- image_alt: 60–125 символів, описує головний об'єкт фото українською, містить ключове слово (приклад: "Tesla Semi на швидкісній трасі — електричний вантажівка нового покоління").
- image_keywords: 3–5 АНГЛІЙСЬКИХ слів для пошуку стокового фото на Pexels (приклад: "Tesla Semi truck highway", "BMW M3 racing track").
- tags: 3–6 коротких тегів українською (моделі, бренди, технології, тематика).
- slug_source: 3–6 англійських слів для URL (без дієслів-зв'язок, тільки суть).
- meta_description: 150–160 символів — для SEO meta тегу. Має містити ключове слово і заклик до дії (наприклад "Дізнайтеся більше"). Це окреме поле від excerpt.
- faq: масив з РІВНО 4 пар питання-відповідь у форматі [{"q": "...", "a": "..."}]. Це критично для AEO (Answer Engine Optimization) — питання забезпечують featured snippets у Google і відповіді в AI пошуку (Perplexity, ChatGPT Search, Gemini).
  ВИМОГИ ДО faq:
  • Питання — як їх би ставив користувач у Google. Природна жива мова. Приклади: "Скільки коштує Tesla Semi?", "Коли вийде нова BMW M3?", "Чи є Hyundai Ioniq 5 надійним?", "Який запас ходу у Rivian R1T?".
  • Перше питання має містити основне ключове слово.
  • Відповідь — 30–60 слів, ФАКТИЧНА, стисла, починається з прямої відповіді (без "ну" / "звичайно"). Може бути цитованою як featured snippet.
  • Всі 4 питання різні, охоплюють: 1) що це таке, 2) ціна / коли вийде, 3) ключова характеристика, 4) порівняння або альтернатива.
  • Без вигаданих цифр. Якщо точної відповіді немає у джерелі — давай загальнодоступний контекст або "поки невідомо, очікуються офіційні дані".

Поверни ВИКЛЮЧНО валідний JSON, без жодного тексту до чи після:
{
  "title": "...",
  "slug_source": "english phrase 3-6 words",
  "excerpt": "...",
  "meta_description": "150-160 символів з ключовим словом і CTA",
  "content_html": "<p>...</p><h2>...</h2><p>...</p><h2>...</h2><ul><li><strong>...</strong>: ...</li>...</ul><h2>Висновок</h2><p>...</p>",
  "tags": ["тег1", "тег2", "тег3"],
  "image_keywords": "english keywords for stock photo",
  "image_alt": "український опис фото з ключовим словом",
  "faq": [
    {"q": "Питання 1?", "a": "Відповідь 1."},
    {"q": "Питання 2?", "a": "Відповідь 2."},
    {"q": "Питання 3?", "a": "Відповідь 3."},
    {"q": "Питання 4?", "a": "Відповідь 4."}
  ]
}"""


def rewrite_article(title: str, content: str, url: str) -> dict[str, Any]:
    """
    Rewrite an English article into Ukrainian, returning a dict with:
      title, slug, excerpt, content_html, tags, image_keywords
    Adds the source link to content_html before returning.
    """
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    user_message = (
        f"ОРИГІНАЛЬНИЙ ЗАГОЛОВОК: {title}\n\n"
        f"ОРИГІНАЛЬНИЙ ТЕКСТ:\n{content}\n\n"
        f"Створи українську SEO-статтю згідно з вимогами системи.\n\n"
        f"ОБОВ'ЯЗКОВО: тіло content_html має містити НЕ МЕНШЕ 500 і НЕ БІЛЬШЕ 700 слів "
        f"(рахуй усі слова в усіх <p>, <h2>, <li> разом). Менше 500 слів — неприпустимо.\n\n"
        f"АЛГОРИТМ: спочатку напиши чернетку, потім порахуй слова. Якщо менше 500 — "
        f"РОЗГОРНИ кожен абзац ще на 1–2 речення з контекстом про:\n"
        f"  • історію та позиціювання моделі/бренду на ринку,\n"
        f"  • тренди в сегменті (EV, седан, SUV тощо) у 2026 році,\n"
        f"  • як ця новина вписується у стратегію виробника,\n"
        f"  • що варто знати українським водіям про цю модель або бренд.\n"
        f"Без вигаданих цифр — лише загальновідомі ринкові факти.\n\n"
        f"Бульти в <ul>: кожен <li> — мінімум 2, бажано 3 повні речення. "
        f"Не одне коротке речення з двокрапкою."
    )

    log.info("Calling OpenAI for rewrite...")
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        response_format={"type": "json_object"},
        temperature=0.7,
        max_tokens=4500,
    )

    raw = response.choices[0].message.content
    if not raw:
        raise RuntimeError("OpenAI returned empty response")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        log.error(f"OpenAI returned invalid JSON: {raw[:500]}")
        raise RuntimeError("OpenAI did not return valid JSON") from e

    # Validate required fields.
    required = [
        "title", "excerpt", "meta_description", "content_html",
        "tags", "image_keywords", "image_alt", "faq",
    ]
    missing = [k for k in required if k not in data]
    if missing:
        raise RuntimeError(f"OpenAI response missing fields: {missing}")

    # Sanity-check faq shape so downstream rendering doesn't crash.
    if not isinstance(data["faq"], list):
        data["faq"] = []
    data["faq"] = [
        {"q": str(item.get("q", "")).strip(), "a": str(item.get("a", "")).strip()}
        for item in data["faq"]
        if isinstance(item, dict) and item.get("q") and item.get("a")
    ]

    # Build the slug from the English slug_source if present, otherwise the title.
    slug_source = data.get("slug_source") or data["title"]
    data["slug"] = slugify(slug_source, max_length=70)[:70].rstrip("-") or "post"

    # Stash the original title and URL so main.py can build the footer
    # (photo credit + source link) after the image is selected.
    data["source_url"] = url
    data["source_title"] = title

    # Ensure tags is a list of strings.
    if not isinstance(data["tags"], list):
        data["tags"] = []
    data["tags"] = [str(t).strip() for t in data["tags"] if str(t).strip()][:8]

    log.info(f"Rewrite OK. New title: {data['title']}")
    return data


def escape_html(s: str) -> str:
    """Minimal HTML escape for attribute/text content."""
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
    )
