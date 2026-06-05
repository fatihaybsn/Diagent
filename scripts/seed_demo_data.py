"""Seed demo data using the demo support bot agent.

Usage::

    # From project root (API must be running)
    python -m scripts.seed_demo_data
"""

from __future__ import annotations

import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    from diagent.adapters.demo_support_bot.agent import run_support_bot

    logger.info("=" * 60)
    logger.info("Senaryo 1: Normal başarılı run")
    logger.info("=" * 60)
    result = run_support_bot(
        "Siparişimin kargo durumu nedir?",
        tool_calls=1,
        tool_error_count=0,
    )
    logger.info("Sonuç: %s\n", result)
    logger.info("✅ Demo seed tamamlandı — 1 run oluşturuldu.")


if __name__ == "__main__":
    main()
