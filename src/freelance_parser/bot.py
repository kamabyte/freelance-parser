from __future__ import annotations

import asyncio
import html
import logging
import statistics
from datetime import datetime, timezone
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from .config import Config
from .enrich import fetch_full_description
from .feed import fetch_all
from .models import Project
from .proposal import generate_draft
from .score import score_project
from .store import Store

log = logging.getLogger(__name__)

# Pause between notifications so a large batch (e.g. threshold=0 firehose mode)
# stays under Telegram's per-chat flood limit.
SEND_DELAY_SECONDS = 0.4

# Touched after every poll; the Docker HEALTHCHECK fails when it goes stale.
HEARTBEAT = Path("/tmp/freelance-parser.heartbeat")


def _format_budget(budget: int | None) -> str:
    if not budget:
        return "по договорённости"
    return f"{budget:,} ₽".replace(",", " ")


def _format_lag(seconds: int) -> str:
    minutes = seconds // 60
    if minutes < 1:
        return "<1 мин"
    if minutes < 60:
        return f"{minutes} мин"
    return f"{minutes // 60} ч {minutes % 60} мин"


def _format_project(p: Project) -> str:
    stats = f"💰 {_format_budget(p.budget)}   |   ⭐ {p.score}"
    if p.lag_seconds is not None:
        stats += f"   |   ⏱ {_format_lag(p.lag_seconds)} назад"
    head = (
        f"<b>{html.escape(p.title)}</b>\n"
        f"🏷 {html.escape(p.category)}\n"
        f"{stats}"
    )
    reasons = "\n".join(f"• {html.escape(r)}" for r in p.reasons)
    link = f'<a href="{html.escape(p.link)}">Открыть проект ↗</a>'
    return f"{head}\n\n{reasons}\n\n{link}" if reasons else f"{head}\n\n{link}"


def _keyboard(pid: int, stage: str = "new") -> InlineKeyboardMarkup:
    if stage == "new":
        rows = [[
            InlineKeyboardButton("📝 Черновик", callback_data=f"draft:{pid}"),
            InlineKeyboardButton("🙈 Скрыть", callback_data=f"skip:{pid}"),
        ]]
    elif stage == "drafted":
        rows = [[
            InlineKeyboardButton("✅ Откликнулся", callback_data=f"applied:{pid}"),
            InlineKeyboardButton("🏆 Взяли", callback_data=f"won:{pid}"),
        ]]
    else:  # "applied"
        rows = [[InlineKeyboardButton("🏆 Взяли", callback_data=f"won:{pid}")]]
    return InlineKeyboardMarkup(rows)


def _resolve_target(cfg: Config, store: Store) -> tuple[str | None, int | None]:
    """Where to post: .env wins, then whatever /start last captured."""
    chat_id = cfg.telegram_chat_id or store.get_setting("chat_id")
    topic_id = cfg.telegram_topic_id
    if topic_id is None:
        stored = store.get_setting("topic_id")
        topic_id = int(stored) if stored and stored.lstrip("-").isdigit() else None
    return chat_id, topic_id


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    store: Store = context.application.bot_data["store"]
    chat_id = str(update.effective_chat.id)
    thread_id = update.message.message_thread_id  # set when sent inside a forum topic
    store.set_setting("chat_id", chat_id)
    if thread_id is not None:
        store.set_setting("topic_id", str(thread_id))

    lines = [
        "✅ Готово. Буду присылать подходящие проекты с fl.ru сюда.",
        f"chat_id: <code>{chat_id}</code>",
    ]
    if thread_id is not None:
        lines.append(f"topic_id: <code>{thread_id}</code>")
    lines.append("\nМожно закрепить их в переменных окружения TELEGRAM_CHAT_ID / TELEGRAM_TOPIC_ID.")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    store: Store = context.application.bot_data["store"]
    c = store.counts()
    lines = [
        f"📊 Всего в базе: {c['total']}",
        f"Уведомлений отправлено: {c['notified']}",
        f"Откликнулся: {c['applied']}",
        f"Взяли в работу: {c['won']}",
    ]
    lags = store.recent_lags(days=7)
    if lags:
        p90 = lags[min(len(lags) - 1, int(len(lags) * 0.9))]
        lines.append(
            f"\n⏱ Задержка за 7 дней (проектов: {len(lags)}): "
            f"медиана {_format_lag(int(statistics.median(lags)))}, "
            f"90% — до {_format_lag(p90)}, максимум {_format_lag(lags[-1])}"
        )
    await update.message.reply_text("\n".join(lines))


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    cfg: Config = context.application.bot_data["cfg"]
    store: Store = context.application.bot_data["store"]

    action, _, sid = query.data.partition(":")
    if not sid.isdigit():
        return
    pid = int(sid)
    p = store.get(pid)
    if p is None:
        return

    if action == "skip":
        store.set_decision(pid, "skip")  # record before deleting — keeps the signal
        try:
            await query.message.delete()
        except Exception:
            # e.g. message older than 48h or missing delete permission — just drop buttons
            log.warning("could not delete message for project %s, removing buttons instead", pid)
            await query.edit_message_reply_markup(reply_markup=None)
    elif action == "applied":
        store.set_decision(pid, "applied")
        await query.edit_message_reply_markup(reply_markup=_keyboard(pid, "applied"))
    elif action == "won":
        store.set_decision(pid, "won")
        await query.edit_message_reply_markup(reply_markup=None)
    elif action == "draft":
        # Reply in the same topic the notification was posted to.
        thread_id = query.message.message_thread_id
        await context.bot.send_chat_action(
            query.message.chat_id, ChatAction.TYPING, message_thread_id=thread_id
        )
        full = await fetch_full_description(p.link, p.description)
        draft = await generate_draft(p, full, cfg)
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            message_thread_id=thread_id,
            text=draft,
            reply_markup=_keyboard(pid, "drafted"),
        )


async def poll_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = context.application.bot_data["cfg"]
    store: Store = context.application.bot_data["store"]
    chat_id, topic_id = _resolve_target(cfg, store)

    # On an empty DB the whole feed is backlog; its age says nothing about our lag.
    track_lag = not store.is_empty()
    projects = await fetch_all(cfg.categories)
    now = datetime.now(timezone.utc)
    notified = 0
    for p in projects:
        p.score, p.reasons = score_project(p, cfg)
        if track_lag and p.published_at:
            p.lag_seconds = max(0, int((now - p.published_at).total_seconds()))
        pid = store.add_if_new(p)
        if pid is None:
            continue  # already seen
        if p.score >= cfg.score_threshold and chat_id:
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    message_thread_id=topic_id,
                    text=_format_project(p),
                    reply_markup=_keyboard(pid),
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
                store.mark_notified(pid)
                notified += 1
                await asyncio.sleep(SEND_DELAY_SECONDS)
            except Exception:
                log.exception("failed to send notification for project %s", pid)

    if not chat_id:
        log.info("poll: %d fetched — no target yet; send /start in the topic or set TELEGRAM_CHAT_ID", len(projects))
    else:
        log.info("poll: %d fetched, %d new notifications (chat=%s topic=%s)", len(projects), notified, chat_id, topic_id)
    HEARTBEAT.touch()


def build_app(cfg: Config) -> Application:
    if not cfg.telegram_token:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN is not set. Create a bot via @BotFather and add the "
            "token to .env (see .env.example)."
        )

    store = Store(cfg.db_path)
    app = Application.builder().token(cfg.telegram_token).build()
    app.bot_data["cfg"] = cfg
    app.bot_data["store"] = store

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CallbackQueryHandler(on_button))
    app.job_queue.run_repeating(poll_job, interval=cfg.poll_interval_seconds, first=5)
    return app
