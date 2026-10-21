from __future__ import annotations

import re
from functools import lru_cache

from .config import Config
from .models import Project


@lru_cache(maxsize=8)
def _compile_keywords(keywords: tuple[str, ...]) -> tuple[tuple[str, re.Pattern], ...]:
    """Word-boundary patterns so short tokens don't match inside other words.

    e.g. "бот" must match «бот»/«чат-бот» but NOT «работа»/«доработка».
    """
    return tuple((kw, re.compile(r"\b" + re.escape(kw), re.IGNORECASE)) for kw in keywords)

# Matches "Бюджет: 3 000 ₽" (spaces / non-breaking spaces inside the number).
_BUDGET_RE = re.compile(r"Бюджет[:\s]*([\d\s ]+)", re.IGNORECASE)


def parse_budget(text: str) -> int | None:
    """Extract a RUB budget from a title/description, or None if not specified."""
    m = _BUDGET_RE.search(text or "")
    if not m:
        return None
    digits = re.sub(r"\D", "", m.group(1))
    return int(digits) if digits else None


def score_project(p: Project, cfg: Config) -> tuple[int, list[str]]:
    """Rule-based 0..100 fit score plus human-readable reasons.

    Tune the weights and keyword lists in config.yaml, not here.
    """
    haystack = f"{p.title}\n{p.description}\n{p.category}".lower()
    score = 0
    reasons: list[str] = []

    # Budget floor is a hard reject (only when a budget is actually stated).
    if cfg.budget_floor and p.budget is not None and p.budget < cfg.budget_floor:
        return 0, [f"Бюджет {p.budget}₽ ниже порога {cfg.budget_floor}₽ — отклонено"]

    # Primary stack keywords (capped so one project can't run away on keywords alone).
    patterns = _compile_keywords(tuple(cfg.stack_primary))
    matched = sorted({kw for kw, pat in patterns if pat.search(haystack)})
    if matched:
        pts = min(len(matched) * 12, 48)
        score += pts
        reasons.append(f"Стек: {', '.join(matched)} (+{pts})")

    # Subcategory is an exact, curated signal — weight it heavily.
    if any(p.subcategory.lower() == g.lower() for g in cfg.good_subcategories):
        score += 25
        reasons.append(f"Подкатегория «{p.subcategory}» (+25)")

    # Budget bands.
    if p.budget is not None:
        if p.budget >= 50000:
            score += 20
            reasons.append(f"Бюджет {p.budget}₽ (+20)")
        elif p.budget >= 20000:
            score += 12
            reasons.append(f"Бюджет {p.budget}₽ (+12)")
        elif p.budget >= 5000:
            score += 6
            reasons.append(f"Бюджет {p.budget}₽ (+6)")

    # Negative keywords (test tasks, unpaid, etc.).
    neg = sorted({kw for kw in cfg.negative_keywords if kw in haystack})
    if neg:
        penalty = 30 * len(neg)
        score -= penalty
        reasons.append(f"Стоп-слова: {', '.join(neg)} (-{penalty})")

    score = max(0, min(100, score))
    return score, reasons
