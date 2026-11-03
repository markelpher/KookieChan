"""Criação, supervisão e cancelamento de tarefas em segundo plano do bot."""

import asyncio
import logging

logger = logging.getLogger(__name__)


def supervise_task(bot, coroutine, *, name, owner):
    tasks = getattr(bot, "_kookie_background_tasks", None)
    if tasks is None:
        tasks = bot._kookie_background_tasks = set()
    task = asyncio.create_task(coroutine)
    # create_task pode ser substituído por um capturador nos testes.
    if task is None:
        return None
    task.set_name(name)
    tasks.add(task)
    owners = getattr(bot, "_kookie_background_task_owners", None)
    if owners is None:
        owners = bot._kookie_background_task_owners = {}
    owners[task] = owner

    def finished(done):
        tasks.discard(done)
        owners.pop(done, None)
        if done.cancelled():
            return
        error = done.exception()
        if error:
            logger.warning(
                "Tarefa em segundo plano %s falhou (%s).", name, type(error).__name__
            )

    task.add_done_callback(finished)
    return task


async def cancel_supervised_tasks(bot, *, owner=None):
    owners = getattr(bot, "_kookie_background_task_owners", {})
    tasks = tuple(
        task
        for task in getattr(bot, "_kookie_background_tasks", ())
        if owner is None or owners.get(task) == owner
    )
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
