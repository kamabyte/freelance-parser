from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime

# https://www.fl.ru/projects/5526922/<slug>.html — the slug follows the title, the id never changes.
_ID_RE = re.compile(r"/projects/(\d+)/")


@dataclass
class Project:
    """A single freelance project parsed from an fl.ru RSS feed."""

    link: str
    title: str
    description: str = ""
    # "<MainCategory> / <Subcategory>", e.g. "Программирование / Разработка Чат-ботов"
    category: str = ""
    budget: int | None = None  # in RUB; None means "по договорённости"
    pub_date: str = ""

    # filled in after scoring / loading from the DB
    id: int | None = None
    score: int = 0
    reasons: list[str] = field(default_factory=list)
    # seconds from fl.ru publishing it to our first sighting; None when unknown
    lag_seconds: int | None = None

    @property
    def fl_id(self) -> int | None:
        m = _ID_RE.search(self.link)
        return int(m.group(1)) if m else None

    @property
    def published_at(self) -> datetime | None:
        try:
            return parsedate_to_datetime(self.pub_date)
        except (TypeError, ValueError):
            return None

    @property
    def subcategory(self) -> str:
        return self.category.split("/")[-1].strip() if "/" in self.category else self.category.strip()
