"""In-process evaluation queue.

Evaluations are persisted with status=queued and their ids are pushed onto an asyncio queue
consumed by N worker tasks. Because state lives in the database, a restart simply re-enqueues
whatever was left queued/running. No external broker is needed for a single-node deployment;
swapping this for Celery/arq later only touches this module.
"""

import asyncio
import logging
from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ml.base import MLClient
from app.services import evaluations as evaluation_service

log = logging.getLogger(__name__)


class EvaluationQueue:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], ml: MLClient, workers: int = 3
    ) -> None:
        self._session_factory = session_factory
        self._ml = ml
        self._workers = workers
        self._queue: asyncio.Queue[int] = asyncio.Queue()
        self._tasks: list[asyncio.Task[None]] = []
        self._inflight: set[int] = set()
        self._processed = 0
        self._failed = 0

    # --- lifecycle ---

    async def start(self) -> None:
        if self._tasks:
            return
        async with self._session_factory() as session:
            leftovers = await evaluation_service.pending_evaluation_ids(session)
        if leftovers:
            log.info("re-enqueueing %d unfinished evaluations", len(leftovers))
            self.enqueue_many(leftovers)
        self._tasks = [
            asyncio.create_task(self._worker(i), name=f"eval-worker-{i}")
            for i in range(self._workers)
        ]

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

    # --- producer side ---

    def enqueue(self, evaluation_id: int) -> None:
        self._queue.put_nowait(evaluation_id)

    def enqueue_many(self, ids: Iterable[int]) -> None:
        for i in ids:
            self.enqueue(i)

    async def join(self) -> None:
        """Wait until every enqueued evaluation has been processed (used in tests)."""
        await self._queue.join()

    def stats(self) -> dict[str, int]:
        return {
            "workers": len(self._tasks),
            "queued": self._queue.qsize(),
            "running": len(self._inflight),
            "processed": self._processed,
            "failed": self._failed,
        }

    # --- consumer side ---

    async def _worker(self, worker_id: int) -> None:
        log.info("worker %d started", worker_id)
        while True:
            evaluation_id = await self._queue.get()
            self._inflight.add(evaluation_id)
            try:
                async with self._session_factory() as session:
                    ev = await evaluation_service.run_evaluation(session, evaluation_id, self._ml)
                if ev is not None and ev.status.value == "failed":
                    self._failed += 1
                self._processed += 1
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — a worker must survive any single bad job
                self._failed += 1
                log.exception(
                    "worker %d: unexpected error on evaluation %s", worker_id, evaluation_id
                )
            finally:
                self._inflight.discard(evaluation_id)
                self._queue.task_done()
