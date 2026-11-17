"""pygeoapi process manager backed by the process jobs table.

Synchronous executions run inline exactly as pygeoapi's ``Dummy`` manager runs
them: same outputs, failure body and status, and no job row, so they never
depend on the database. Asynchronous executions of processes that declare
``async-execute`` are queued for ``process-worker``.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from pygeoapi.process.base import (
    BaseProcessor,
    JobNotFoundError,
    JobResultNotFoundError,
)
from pygeoapi.process.manager.base import BaseManager
from pygeoapi.util import (
    JobStatus,
    ProcessExecutionMode,
    RequestedProcessExecutionMode,
    RequestedResponse,
    Subscriber,
)

from agri_i18n import get_locale

from .schema import DEFAULT_TABLE
from .store import JobStore, NewJob

logger = logging.getLogger(__name__)

JSON_MIMETYPE: str = "application/json"


def failure_outputs(err: Exception) -> dict[str, str]:
    """The failure body pygeoapi's ``Dummy`` manager returns."""
    return {
        "code": "InvalidParameterValue",
        "description": f"Error executing process: {err}",
    }


def wrap_outputs(outputs: Any, requested_response: str | None) -> Any:
    """Apply the OGC ``document`` response wrapping when it was requested."""
    if requested_response == RequestedResponse.document.value:
        return {"outputs": [outputs]}
    return outputs


def supports_async(processor: BaseProcessor) -> bool:
    """Whether the process declares ``async-execute``."""
    return ProcessExecutionMode.async_execute.value in processor.metadata.get(
        "jobControlOptions", []
    )


class AgriJobManager(BaseManager):
    """Job manager storing jobs in PostgreSQL and queueing async ones."""

    def __init__(
        self, manager_def: dict[str, Any], store: JobStore | None = None
    ) -> None:
        super().__init__(manager_def)
        self.is_async = True
        self.supports_subscribing = False
        connection = manager_def.get("connection") or {}
        self._table: str = connection.get("table", DEFAULT_TABLE)
        self._store = store

    @property
    def store(self) -> JobStore:
        if self._store is None:
            self._store = JobStore(self._table)
        return self._store

    def get_jobs(
        self,
        status: JobStatus | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> dict[str, Any]:
        jobs, total = self.store.page(
            limit, offset, status.value if status is not None else None
        )
        return {"jobs": jobs, "numberMatched": total}

    def get_job(self, job_id: str) -> dict[str, Any]:
        job = self.store.get(job_id)
        if job is None:
            raise JobNotFoundError()
        return job

    def get_job_result(self, job_id: str) -> tuple[Any, ...]:
        job = self.get_job(job_id)
        if job["status"] != JobStatus.successful.value:
            return (None,)
        if job["result"] is None:
            raise JobResultNotFoundError()
        return job["mimetype"], job["result"]

    def delete_job(self, job_id: str) -> bool:
        if not self.store.delete(job_id):
            raise JobNotFoundError()
        return True

    def execute_process(
        self,
        process_id: str,
        data_dict: dict[str, Any],
        execution_mode: RequestedProcessExecutionMode | None = None,
        requested_outputs: dict[str, Any] | None = None,
        subscriber: Subscriber | None = None,
        requested_response: str | None = RequestedResponse.raw.value,
    ) -> tuple[str, str, Any, JobStatus, dict[str, str] | None]:
        processor = self.get_processor(process_id)
        job_id = str(uuid4())
        processor.set_job_id(job_id)
        job = NewJob(
            identifier=job_id,
            process_id=process_id,
            locale=get_locale(),
            inputs=data_dict,
            requested_outputs=requested_outputs,
            requested_response=requested_response,
        )

        if (
            execution_mode == RequestedProcessExecutionMode.respond_async
            and supports_async(processor)
        ):
            self.store.insert_accepted(job)
            headers = {
                "Preference-Applied": RequestedProcessExecutionMode.respond_async.value
            }
            return job_id, JSON_MIMETYPE, None, JobStatus.accepted, headers

        headers = (
            None
            if execution_mode is None
            else {"Preference-Applied": RequestedProcessExecutionMode.wait.value}
        )
        mimetype, outputs, status = self._execute_sync(processor, job)
        return job_id, mimetype, outputs, status, headers

    def _execute_sync(
        self, processor: BaseProcessor, job: NewJob
    ) -> tuple[str, Any, JobStatus]:
        mimetype = JSON_MIMETYPE
        try:
            mimetype, outputs = processor.execute(
                job.inputs, outputs=job.requested_outputs
            )
            status = JobStatus.successful
        except Exception as err:
            logger.exception("Process %s failed", job.process_id)
            outputs = failure_outputs(err)
            status = JobStatus.failed
        return mimetype, wrap_outputs(outputs, job.requested_response), status

    def __repr__(self) -> str:
        return f"<AgriJobManager> {self.name}"
