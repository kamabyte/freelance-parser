from __future__ import annotations

import logging

from anthropic import AsyncAnthropic

from .config import Config
from .models import Project

log = logging.getLogger(__name__)

# Gen 1: a single general-purpose template. Gen 2 will append the user's own
# past proposals as few-shot examples so drafts read in their voice.
SYSTEM_TEMPLATE = """\
Ты помогаешь фрилансеру (профиль ниже) писать отклики на проекты на бирже fl.ru.

Пиши на русском. Тон: профессиональный, по делу, человечный и уверенный — без воды,
без штампов, без «Здравствуйте, меня зовут...». Структура отклика:
1) одна фраза, показывающая, что ты понял задачу;
2) 2–4 предложения о том, как конкретно ты бы её решил, со ссылкой на релевантный
   опыт из профиля;
3) при необходимости — один короткий уточняющий вопрос;
4) короткое завершение про готовность обсудить детали.
Объём 90–160 слов. Не выдумывай опыт, которого нет в профиле. Не называй точные
цены и сроки — предложи обсудить их.

ПРОФИЛЬ ФРИЛАНСЕРА:
{profile}
"""

USER_TEMPLATE = """\
Напиши отклик на этот проект.

Заголовок: {title}
Категория: {category}
Бюджет: {budget}
Описание:
{description}
"""


async def generate_draft(project: Project, full_description: str, cfg: Config) -> str:
    if not cfg.anthropic_api_key:
        return "⚠️ ANTHROPIC_API_KEY не задан — черновик не сгенерировать. Добавь ключ в переменные окружения."

    profile = cfg.profile_path.read_text(encoding="utf-8") if cfg.profile_path.exists() else ""
    budget = f"{project.budget} ₽" if project.budget else "по договорённости"
    user = USER_TEMPLATE.format(
        title=project.title,
        category=project.category,
        budget=budget,
        description=(full_description or project.description or "—"),
    )
    # Stable prefix first (cache_control) so Gen 2's growing few-shot examples cache.
    system = [
        {
            "type": "text",
            "text": SYSTEM_TEMPLATE.format(profile=profile),
            "cache_control": {"type": "ephemeral"},
        }
    ]

    client = AsyncAnthropic(api_key=cfg.anthropic_api_key)
    kwargs = dict(
        model=cfg.model,
        max_tokens=4000,
        thinking={"type": "adaptive"},
        output_config={"effort": "medium"},
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    try:
        msg = await client.messages.create(**kwargs)
    except TypeError:
        # Older SDK without adaptive thinking / output_config support — degrade gracefully.
        kwargs.pop("thinking", None)
        kwargs.pop("output_config", None)
        try:
            msg = await client.messages.create(**kwargs)
        except Exception as e:
            log.exception("draft generation failed")
            return f"⚠️ Не удалось сгенерировать черновик: {e}"
    except Exception as e:
        log.exception("draft generation failed")
        return f"⚠️ Не удалось сгенерировать черновик: {e}"

    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    return text or "⚠️ Пустой ответ модели — попробуй ещё раз."
