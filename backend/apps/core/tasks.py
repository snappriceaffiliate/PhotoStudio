import logging

from procrastinate.contrib.django import app

logger = logging.getLogger(__name__)


@app.task(name="core.ping")
def ping(message: str = "pong") -> str:
    """Smoke-test task: proves the worker reads jobs from PostgreSQL."""
    logger.info("ping task ran: %s", message)
    return message
