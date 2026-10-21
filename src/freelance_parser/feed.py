from __future__ import annotations

import asyncio
import html
import logging

import feedparser
import httpx
from selectolax.parser import HTMLParser

from .models import Project
from .score import parse_budget

log = logging.getLogger(__name__)

RSS_URL = "https://www.fl.ru/rss/all.xml"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
)


def _strip_html(s: str) -> str:
    if not s:
        return ""
    return HTMLParser(s).text(separator=" ", strip=True)


async def fetch_category(client: httpx.AsyncClient, category: int) -> list[Project]:
    resp = await client.get(
        RSS_URL, params={"category": category}, headers={"User-Agent": UA}, timeout=30.0
    )
    resp.raise_for_status()
    parsed = feedparser.parse(resp.content)

    projects: list[Project] = []
    for e in parsed.entries:
        title = html.unescape(getattr(e, "title", "") or "")
        summary = _strip_html(getattr(e, "summary", "") or "")
        tags = getattr(e, "tags", None) or []
        category_label = tags[0].get("term", "") if tags else ""
        projects.append(
            Project(
                link=getattr(e, "link", "") or "",
                title=title,
                description=summary,
                category=category_label,
                budget=parse_budget(f"{title} {summary}"),
                pub_date=getattr(e, "published", "") or "",
            )
        )
    return projects


async def fetch_all(categories: list[int]) -> list[Project]:
    """Fetch every configured category feed concurrently. Failures are logged, not fatal."""
    async with httpx.AsyncClient(follow_redirects=True) as client:
        results = await asyncio.gather(
            *(fetch_category(client, c) for c in categories), return_exceptions=True
        )

    projects: list[Project] = []
    for category, result in zip(categories, results):
        if isinstance(result, Exception):
            log.warning("feed category=%s failed: %s", category, result)
            continue
        projects.extend(result)
    return projects
