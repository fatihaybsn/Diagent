"""Celery application instance.

Broker and backend both point to Redis.
Task modules are auto-discovered from `diagent.workers.tasks`.
"""

import os

from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "diagent",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

# Auto-discover tasks in the same package
celery_app.autodiscover_tasks(["diagent.workers"])
