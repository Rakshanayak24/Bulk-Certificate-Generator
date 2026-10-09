# Bulk Certificate Generator

A FastAPI service that accepts one batch of recipients, validates and processes each entry independently, creates a PDF certificate for every valid recipient, and records job results in SQLite.

## Requirements and setup

Python 3.10 or newer is required.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
```

The default database is `./data/certificates.db`; generated PDFs are stored under `./data/certificates/`. Both locations are created as needed. Set `DATABASE_URL` and `CERTIFICATE_STORAGE` to change them.

## Run the API

```powershell
uvicorn certificate_api.main:app --reload
```

Open `http://127.0.0.1:8000/docs` for the interactive API documentation.

## Endpoints

### Submit a batch

`POST /api/jobs`

```json
{
  "recipients": [
    {
      "full_name": "Ada Lovelace",
      "email": "ada@example.com",
      "course_name": "Introduction to Computing",
      "issue_date": "2026-01-15"
    }
  ]
}
```

The batch must contain 1 to 1,000 entries. Each recipient needs a nonblank `full_name` and `course_name`, a valid `email`, and an ISO `issue_date` (`YYYY-MM-DD`). Unknown fields are rejected for that recipient. Individual invalid entries are recorded as failures while other entries continue.

The `201` response includes the job ID, status, counts, and an ordered result for each recipient. A successful result includes a `certificate_url`; failed results include a safe validation or generation error. Job statuses are `COMPLETED` and `COMPLETED_WITH_ERRORS`.

### Check job status and results

`GET /api/jobs/{job_id}`

Returns the same job summary and per-recipient results as the submission response. Unknown IDs return `404`.

### Download a certificate

`GET /api/jobs/{job_id}/certificates/{recipient_id}`

Returns the generated PDF as an attachment. A certificate belonging to a different job or an unknown recipient returns `404`.

## Architecture and design decisions

- `certificate_api/main.py` defines request validation, SQLAlchemy models, API routes, and job processing. `certificate_api/certificates.py` renders the one predefined landscape PDF design.
- The service processes a batch synchronously. This avoids a separate broker/worker dependency and means the returned job result is final. SQLite persists jobs and recipient outcomes across restarts; files are stored by opaque job and recipient IDs.
- Validation and generation happen per recipient, so one invalid record or renderer error does not stop the rest of the batch. Results include stable per-recipient IDs, success/failure state, and error details appropriate for clients.
- Generation exceptions are isolated and reported by exception type; raw filesystem or library messages are not exposed. Uploaded data is not used to construct filesystem paths.
- This is a single-process service. For very large or latency-sensitive batches, a production deployment could move processing to a durable task queue and expose intermediate progress. The current synchronous design is suitable for the assignment's bounded batch size.

## Tests

```powershell
python -m pip install -e ".[test]"
pytest
```

Tests cover request validation, job creation and status, real PDF generation and download, recipient-level validation failures, independent generation failures, and job-scoped certificate access.
