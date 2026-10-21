from __future__ import annotations

import logging

from .bot import build_app
from .config import load_config


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # httpx logs every request URL at INFO, and Bot API URLs contain the token.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    cfg = load_config()
    app = build_app(cfg)
    logging.getLogger(__name__).info(
        "Starting freelance-parser (categories=%s, interval=%ss, threshold=%s)",
        cfg.categories,
        cfg.poll_interval_seconds,
        cfg.score_threshold,
    )
    # Blocking; runs the polling loop + the repeating feed job until Ctrl-C.
    app.run_polling()


if __name__ == "__main__":
    main()
