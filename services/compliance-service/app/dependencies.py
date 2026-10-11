from fastapi import Request

from app.jobs import ComplianceJobStore


def get_job_store(request: Request) -> ComplianceJobStore:
    return request.app.state.job_store
