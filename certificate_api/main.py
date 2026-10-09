"""FastAPI application and persistence models for bulk certificate jobs."""

import os
import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field, ValidationError, field_validator
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from .certificates import render_certificate


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="PROCESSING")
    total_count: Mapped[int] = mapped_column(Integer)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    recipients: Mapped[list["Recipient"]] = relationship(back_populates="job", cascade="all, delete-orphan")


class Recipient(Base):
    __tablename__ = "recipients"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    index: Mapped[int] = mapped_column(Integer)
    full_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    status: Mapped[str] = mapped_column(String(20))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    certificate_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    job: Mapped[Job] = relationship(back_populates="recipients")


class RecipientInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    course_name: str = Field(min_length=1, max_length=200)
    issue_date: date

    @field_validator("full_name", "course_name")
    @classmethod
    def strip_nonempty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class JobRequest(BaseModel):
    recipients: list[dict[str, Any]] = Field(min_length=1, max_length=1000)


def _safe_error(error: ValidationError) -> str:
    first = error.errors()[0]
    field = ".".join(str(part) for part in first["loc"])
    return f"{field}: {first['msg']}"


def _serialize_job(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "status": job.status,
        "total_count": job.total_count,
        "success_count": job.success_count,
        "failure_count": job.failure_count,
        "created_at": job.created_at.isoformat(),
        "recipients": [
            {
                "id": r.id,
                "index": r.index,
                "full_name": r.full_name,
                "email": r.email,
                "status": r.status,
                "error": r.error,
                "certificate_url": f"/api/jobs/{job.id}/certificates/{r.id}" if r.status == "COMPLETED" else None,
            }
            for r in sorted(job.recipients, key=lambda row: row.index)
        ],
    }


def create_app(
    database_url: str | None = None,
    storage_dir: str | Path | None = None,
    certificate_renderer=render_certificate,
) -> FastAPI:
    db_url = database_url or os.getenv("DATABASE_URL", "sqlite:///./data/certificates.db")
    files_dir = Path(storage_dir or os.getenv("CERTIFICATE_STORAGE", "./data/certificates")).resolve()
    if db_url.startswith("sqlite:///"):
        db_path = Path(db_url.removeprefix("sqlite:///"))
        if not db_path.is_absolute():
            db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(db_url, connect_args={"check_same_thread": False} if db_url.startswith("sqlite") else {})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    app = FastAPI(title="Bulk Certificate Generator", version="1.0.0")
    app.state.engine = engine

    @app.post("/api/jobs", status_code=201)
    def create_job(payload: JobRequest) -> dict[str, Any]:
        job_id = uuid.uuid4().hex
        with sessions() as db:
            job = Job(id=job_id, status="PROCESSING", total_count=len(payload.recipients), created_at=datetime.now(timezone.utc))
            db.add(job)
            db.flush()
            rows: list[tuple[Recipient, dict[str, Any] | None]] = []
            for index, raw in enumerate(payload.recipients):
                recipient_id = uuid.uuid4().hex
                try:
                    normalized = RecipientInput.model_validate(raw)
                    recipient = Recipient(id=recipient_id, job_id=job_id, index=index, full_name=normalized.full_name,
                                          email=str(normalized.email), status="PROCESSING")
                    render_data = normalized.model_dump(mode="json")
                except ValidationError as exc:
                    recipient = Recipient(id=recipient_id, job_id=job_id, index=index,
                                          full_name=raw.get("full_name") if isinstance(raw.get("full_name"), str) else None,
                                          email=raw.get("email") if isinstance(raw.get("email"), str) else None,
                                          status="FAILED", error=_safe_error(exc))
                    render_data = None
                db.add(recipient)
                rows.append((recipient, render_data))
            db.commit()

            for recipient, data in rows:
                if data is None:
                    continue
                target = files_dir / job_id / f"{recipient.id}.pdf"
                try:
                    certificate_renderer(data, target)
                    recipient.status = "COMPLETED"
                    recipient.certificate_path = str(target)
                    job.success_count += 1
                except Exception as exc:  # keep processing the remaining recipients
                    recipient.status = "FAILED"
                    recipient.error = f"Certificate generation failed: {type(exc).__name__}"
                    job.failure_count += 1
                db.commit()
            job.failure_count = sum(r.status == "FAILED" for r, _ in rows)
            job.status = "COMPLETED" if job.failure_count == 0 else "COMPLETED_WITH_ERRORS"
            db.commit()
            db.refresh(job)
            return _serialize_job(job)

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        with sessions() as db:
            job = db.get(Job, job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="Job not found")
            return _serialize_job(job)

    @app.get("/api/jobs/{job_id}/certificates/{recipient_id}")
    def get_certificate(job_id: str, recipient_id: str) -> Response:
        with sessions() as db:
            recipient = db.scalar(select(Recipient).where(Recipient.id == recipient_id, Recipient.job_id == job_id))
            if recipient is None:
                raise HTTPException(status_code=404, detail="Certificate not found")
            if recipient.status != "COMPLETED" or not recipient.certificate_path:
                raise HTTPException(status_code=409, detail="Certificate is not available")
            path = Path(recipient.certificate_path)
            if not path.is_file():
                raise HTTPException(status_code=404, detail="Certificate file is missing")
            download_name = re.sub(r"[^A-Za-z0-9._-]+", "_", recipient.full_name or "certificate")
            return FileResponse(path, media_type="application/pdf", filename=f"{download_name}.pdf")

    return app


app = create_app()
