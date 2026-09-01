import json
import uuid
from datetime import UTC, datetime
from typing import Any

from redis import Redis
from redis.exceptions import RedisError

from app.config import settings


class ComplianceJobStore:
    def __init__(self) -> None:
        self._redis: Redis | None = None
        if settings.redis_enabled:
            self._redis = Redis.from_url(
                settings.redis_url,
                socket_connect_timeout=1,
                socket_timeout=1,
                decode_responses=True,
            )

    def start(self, shipment_id: str) -> str:
        job_id = str(uuid.uuid4())
        self._write(
            job_id,
            {
                "job_id": job_id,
                "shipment_id": shipment_id,
                "status": "RUNNING",
                "started_at": utc_iso(),
            },
        )
        return job_id

    def complete(self, job_id: str, assessment_id: str) -> None:
        self._update(job_id, {"status": "COMPLETED", "assessment_id": assessment_id})

    def fail(self, job_id: str, error: str) -> None:
        self._update(job_id, {"status": "FAILED", "error": error})

    def _update(self, job_id: str, values: dict[str, Any]) -> None:
        current = self._read(job_id)
        current.update(values)
        current["updated_at"] = utc_iso()
        self._write(job_id, current)

    def _read(self, job_id: str) -> dict[str, Any]:
        if self._redis is None:
            return {"job_id": job_id}
        try:
            raw_value = self._redis.get(key(job_id))
        except RedisError:
            return {"job_id": job_id}
        if raw_value is None:
            return {"job_id": job_id}
        return json.loads(raw_value)

    def _write(self, job_id: str, payload: dict[str, Any]) -> None:
        if self._redis is None:
            return
        try:
            self._redis.setex(key(job_id), 3600, json.dumps(payload))
        except RedisError:
            return


def key(job_id: str) -> str:
    return f"tradetwin:compliance:jobs:{job_id}"


def utc_iso() -> str:
    return datetime.now(UTC).isoformat()
