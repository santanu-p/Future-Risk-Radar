"""Reports API — trigger generation & download intelligence briefs."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from sqlalchemy import select

from frr.api.deps import AnalystUser, CurrentUser, DbSession, TenantOrg, get_tenant_region_filter
from frr.api.schemas import ReportJobCreate, ReportJobOut
from frr.db.models import ReportFormat, ReportJob
from frr.db.session import get_session_factory

router = APIRouter()


async def _generate_in_background(job_id: uuid.UUID) -> None:
    """Run report generation in the background."""
    from frr.services.reports import generate_report

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(select(ReportJob).where(ReportJob.id == job_id))
        job = result.scalar_one_or_none()
        if job:
            await generate_report(session, job)


@router.post("/reports", response_model=ReportJobOut, status_code=status.HTTP_202_ACCEPTED)
async def create_report(
    body: ReportJobCreate,
    background: BackgroundTasks,
    db: DbSession,
    user: AnalystUser,
    org: TenantOrg,
) -> ReportJob:
    """Trigger a new report generation (analyst+ only). Returns immediately."""
    # Validate region access
    allowed = get_tenant_region_filter(org)
    if allowed and body.region_code and body.region_code not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Region not in tenant scope")

    try:
        fmt = ReportFormat(body.report_format)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid format: {body.report_format}")

    job = ReportJob(
        organization_id=org.id if org else user.organization_id,
        region_code=body.region_code,
        report_format=fmt,
        period_start=body.period_start,
        period_end=body.period_end,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    background.add_task(_generate_in_background, job.id)
    return job


@router.get("/reports", response_model=list[ReportJobOut])
async def list_reports(
    db: DbSession,
    user: CurrentUser,
    org: TenantOrg,
    region_code: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[ReportJob]:
    query = select(ReportJob).order_by(ReportJob.created_at.desc())

    if org:
        query = query.where(ReportJob.organization_id == org.id)
    elif user.organization_id:
        query = query.where(ReportJob.organization_id == user.organization_id)

    if region_code:
        query = query.where(ReportJob.region_code == region_code)
    if status_filter:
        query = query.where(ReportJob.status == status_filter)

    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/reports/{report_id}", response_model=ReportJobOut)
async def get_report(report_id: uuid.UUID, db: DbSession, user: CurrentUser) -> ReportJob:
    result = await db.execute(select(ReportJob).where(ReportJob.id == report_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return job


@router.get("/reports/{report_id}/download")
async def download_report(report_id: uuid.UUID, db: DbSession, user: CurrentUser):
    """Return a presigned download URL for the report file."""
    from fastapi.responses import RedirectResponse
    import boto3
    from botocore.config import Config as BotoConfig
    from frr.config import get_settings

    result = await db.execute(select(ReportJob).where(ReportJob.id == report_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Report not found")
    if job.status != "completed" or not job.file_path:
        raise HTTPException(status_code=409, detail="Report not ready for download")

    settings = get_settings()
    s3 = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        config=BotoConfig(signature_version="s3v4"),
    )

    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.reports_s3_bucket, "Key": job.file_path},
        ExpiresIn=3600,
    )
    return RedirectResponse(url=url)
