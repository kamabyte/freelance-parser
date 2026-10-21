from __future__ import annotations

from dataclasses import dataclass, field


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

    @property
    def subcategory(self) -> str:
        return self.category.split("/")[-1].strip() if "/" in self.category else self.category.strip()
