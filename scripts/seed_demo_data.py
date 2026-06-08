"""Seed demo data using the demo support bot agent.

Runs 3 scenarios through the full tracer pipeline:
  1. Normal successful run
  2. Tool errors (3 failures)
  3. Tool loop (same tool called 5 times)

Usage::

    # From project root (API must be running)
    python -m scripts.seed_demo_data

    # Inside Docker
    docker compose exec api python -m scripts.seed_demo_data
"""

from __future__ import annotations

import logging
import sys

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

    logger.info("=" * 60)
    logger.info("Senaryo 2: Tool 3 kez hata veren run")
    logger.info("=" * 60)
    result = run_support_bot(
        "İade talebimi işleme alabilir misiniz?",
        tool_calls=3,
        tool_error_count=3,
        tool_name="refund_processor",
    )
    logger.info("Sonuç: %s\n", result)

    logger.info("=" * 60)
    logger.info("Senaryo 3: Aynı tool 5 kez çağrılan run (loop)")
    logger.info("=" * 60)
    result = run_support_bot(
        "Ödeme yöntemlerini listeleyebilir misiniz?",
        tool_calls=5,
        tool_error_count=0,
        tool_name="payment_lookup",
    )
    logger.info("Sonuç: %s\n", result)

    logger.info("✅ Demo seed tamamlandı — 3 run oluşturuldu.")


if __name__ == "__main__":
    main()
