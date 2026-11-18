"""The liveness probe must not need the database or any upstream service."""

from django.test import Client


def test_healthz_returns_ok_without_database():
    response = Client().get("/healthz/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
