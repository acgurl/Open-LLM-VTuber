import asyncio
from typing import Optional

from loguru import logger


async def cancel_and_wait(
    task: Optional[asyncio.Task],
    *,
    failure_message: str,
    cancel_message: Optional[str] = None,
) -> None:
    """Cancel a task and wait for it, logging unexpected failures."""
    if task is None or task.done():
        return

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        if cancel_message:
            logger.info(cancel_message)
    except Exception:
        logger.exception(failure_message)
