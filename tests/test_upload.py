from pathlib import Path


def test_upload_streams_file_and_returns_queued_job(api_client, fake_db) -> None:
    response = api_client.post(
        "/documents",
        files={"file": ("invoice.pdf", b"%PDF-1.4\nhello", "application/pdf")},
    )

    payload = response.json()
    assert response.status_code == 202
    assert payload["status"] == "queued"
    assert payload["status_url"] == f"/jobs/{payload['job_id']}"
    assert len(fake_db.added) == 1
    assert Path(fake_db.added[0].storage_path).exists()
