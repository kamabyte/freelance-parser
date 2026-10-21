from __future__ import annotations

import logging

import httpx
from selectolax.parser import HTMLParser

from .feed import UA

log = logging.getLogger(__name__)

# Candidate selectors for the full project description on an fl.ru project page.
# The list is best-effort; we always fall back to the RSS summary on failure or
# when nothing better is found, so anti-bot pages never break draft generation.
_DESC_SELECTORS = [
    "[itemprop='description']",
    "#projectp",
    ".b-layout__txt",
    ".project_description",
    ".text-5",
]


async def fetch_full_description(link: str, fallback: str = "") -> str:
    """Best-effort fetch of the full project text. Returns `fallback` on any problem.

    Called only when the user taps "Черновик", so request volume stays low and we
    don't hammer fl.ru (or trip its anti-bot protection) during polling.
    """
    if not link:
        return fallback
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            resp = await client.get(link, headers={"User-Agent": UA})
            resp.raise_for_status()
    except Exception as e:  # network error, anti-bot challenge, timeout, ...
        log.warning("enrich failed for %s: %s", link, e)
        return fallback

    tree = HTMLParser(resp.text)
    best = fallback
    for sel in _DESC_SELECTORS:
        node = tree.css_first(sel)
        if node:
            text = node.text(separator="\n", strip=True)
            if text and len(text) > len(best):
                best = text
    return best
