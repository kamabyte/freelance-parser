# freelance-parser

Monitors [fl.ru](https://www.fl.ru) freelance projects in your categories, scores each
one against your stack, and pushes the good matches to Telegram — with a one-tap button
to generate a tailored proposal draft (via Claude). **No auto-posting:** you review and
send every proposal yourself.

## How it works

```
fl.ru RSS  ──▶  score (your stack + budget)  ──▶  Telegram alert
   (poll)                                              │
                                          tap "📝 Черновик"
                                                       ▼
                              fetch full project text  ──▶  Claude draft
```

The RSS feed already tags each item with its subcategory (`Программирование /
Разработка Чат-ботов`) and puts the budget in the title, so discovery + scoring need
only the lightweight feed. The full project page is fetched **only** when you ask for a
draft, to keep request volume low.

## Setup

1. **Install deps** (uses [uv](https://docs.astral.sh/uv/)):

   ```bash
   uv sync
   ```

2. **Create a Telegram bot:** message [@BotFather](https://t.me/BotFather), send
   `/newbot`, copy the token.

3. **Configure secrets:**

   ```bash
   cp .env.example .env
   ```

   Fill in `TELEGRAM_BOT_TOKEN` and `ANTHROPIC_API_KEY`.

4. **Edit `profile.md`** — add your real experience and a few case studies. This drives
   the proposal drafts; the richer it is, the more human they read.

5. **Run it:**

   ```bash
   uv run freelance-parser
   ```

6. **Open Telegram, find your bot, send `/start`.** The bot remembers your chat and
   starts sending matches. Send `/stats` any time for a summary, including how long
   projects took to reach the bot over the last 7 days (median / 90% / max). Each alert
   shows the same per project: `⏱ 3 мин назад`.

## Telegram controls

Each match comes with buttons:

- **📝 Черновик** — generate a proposal draft, then mark **✅ Откликнулся** / **🏆 Взяли**.
- **🙈 Скрыть** — not interested.

Your decisions are logged in `data/parser.db` — this becomes the training data for
Gen 2 (drafts in your own voice, learned from proposals that won).

## Configuration (`config.yaml`)

| Key | Meaning |
|---|---|
| `categories` | fl.ru RSS category ids to watch |
| `poll_interval_seconds` | how often to poll (default 90s) |
| `score_threshold` | minimum score (0–100) to notify |
| `budget_floor` | hard-reject projects below this RUB budget (0 = off) |
| `stack.primary` | keywords that mark a project as yours |
| `stack.good_subcategories` | exact fl.ru subcategory labels that score high |
| `negative_keywords` | substrings that push a project down |

### fl.ru category ids

`2` Сайты · `5` Программирование · `6` Продвижение (SEO) · `8` Тексты ·
`9` 3D-графика · `12` Реклама и Маркетинг · `13` Аутсорсинг/консалтинг ·
`30` Marketplace · `31` AI · `33` Игры · `34` Мессенджеры · `36` Mobile ·
`38` Crypto · `39` Анимация · `40` Интернет-магазины · `41` Автоматизация бизнеса.

## Deployment

The bot runs as a Docker container from `ghcr.io/kamabyte/freelance-parser`, built by
GitHub Actions on every push to `main`. It needs a volume at `/data` for the SQLite DB
and nothing else: no ports, no domain. Quick start:

```bash
docker run -d --name freelance-parser --restart unless-stopped \
  --env-file .env -v freelance-parser-data:/data \
  ghcr.io/kamabyte/freelance-parser:latest
```

To tune scoring or keep a private profile without rebuilding the image, drop your own
`config.yaml` / `profile.md` into `/data` — they win over the ones baked in.

Running it on [Dokploy](https://dokploy.com) and deploying from your machine via its
API — see [DEPLOY.md](DEPLOY.md).

## Roadmap

- **Gen 1 (this):** RSS → scoring → Telegram → general-purpose draft.
- **Gen 2:** export your real proposals → drafts in your voice; learn from wins.
- **Out of scope (intentionally):** auto-posting responses to fl.ru.

## License

[MIT](LICENSE)
