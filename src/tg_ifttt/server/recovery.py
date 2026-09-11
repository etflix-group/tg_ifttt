"""Restart-safe recovery loop for durable workflow runs."""

import asyncio
from typing import Any

from tg_ifttt.runtime.engine import WorkflowEngine
from tg_ifttt.storage.database import Database


class RecoveryWorker:
    def __init__(self, database: Database, adapter: Any, interval_seconds: float = 15.0) -> None:
        if interval_seconds <= 0:
            raise ValueError("recovery interval must be positive")
        self.database = database
        self.engine = WorkflowEngine(database, adapter)
        self.interval_seconds = interval_seconds
        self._stopped = False

    async def recover_once(self) -> None:
        for run in self.database.runs.list_recoverable_runs():
            await self.engine.resume(run.run_id)

    async def run(self) -> None:
        await self.recover_once()
        while not self._stopped:
            await asyncio.sleep(self.interval_seconds)
            if not self._stopped:
                await self.recover_once()

    def stop(self) -> None:
        self._stopped = True
