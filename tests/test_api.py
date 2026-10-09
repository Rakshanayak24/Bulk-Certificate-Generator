from datetime import date

from fastapi.testclient import TestClient

from certificate_api.main import create_app


def sample(name="Ada Lovelace"):
    return {
        "full_name": name,
        "email": "ada@example.com",
        "course_name": "Introduction to Computing",
        "issue_date": date(2026, 1, 15).isoformat(),
    }


def client_for(tmp_path, renderer=None):
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        storage_dir=tmp_path / "pdfs",
        **({"certificate_renderer": renderer} if renderer else {}),
    )
    return TestClient(app)


def test_create_job_generates_and_retrieves_certificate(tmp_path):
    client = client_for(tmp_path)
    response = client.post("/api/jobs", json={"recipients": [sample()]})
    assert response.status_code == 201
    job = response.json()
    assert job["status"] == "COMPLETED"
    assert (job["total_count"], job["success_count"], job["failure_count"]) == (1, 1, 0)
    recipient = job["recipients"][0]
    assert recipient["status"] == "COMPLETED"
    assert client.get(f"/api/jobs/{job['id']}").json() == job

    pdf = client.get(recipient["certificate_url"])
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF-")


def test_invalid_recipient_is_reported_without_rejecting_valid_entries(tmp_path):
    client = client_for(tmp_path)
    invalid = sample(" ")
    response = client.post("/api/jobs", json={"recipients": [sample(), invalid]})
    assert response.status_code == 201
    job = response.json()
    assert job["status"] == "COMPLETED_WITH_ERRORS"
    assert (job["success_count"], job["failure_count"]) == (1, 1)
    assert [r["status"] for r in job["recipients"]] == ["COMPLETED", "FAILED"]
    assert "full_name" in job["recipients"][1]["error"]


def test_request_validation_and_job_not_found(tmp_path):
    client = client_for(tmp_path)
    assert client.post("/api/jobs", json={"recipients": []}).status_code == 422
    assert client.get("/api/jobs/missing").status_code == 404


def test_generation_failure_does_not_stop_later_recipients(tmp_path):
    def fail_first(data, path):
        if data["full_name"] == "Ada Lovelace":
            raise OSError("disk error")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"%PDF-test")

    client = client_for(tmp_path, renderer=fail_first)
    response = client.post("/api/jobs", json={"recipients": [sample(), sample("Grace Hopper")]})
    job = response.json()
    assert response.status_code == 201
    assert job["status"] == "COMPLETED_WITH_ERRORS"
    assert (job["success_count"], job["failure_count"]) == (1, 1)
    assert [r["status"] for r in job["recipients"]] == ["FAILED", "COMPLETED"]
    assert "OSError" in job["recipients"][0]["error"]
    assert client.get(job["recipients"][0]["certificate_url"] or "/api/jobs/x/certificates/x").status_code == 404


def test_certificate_is_scoped_to_job(tmp_path):
    client = client_for(tmp_path)
    job = client.post("/api/jobs", json={"recipients": [sample()]}).json()
    recipient_id = job["recipients"][0]["id"]
    assert client.get(f"/api/jobs/another-job/certificates/{recipient_id}").status_code == 404
