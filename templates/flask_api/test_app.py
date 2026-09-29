"""Tests for Flask API template."""
import pytest
from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_health_check(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.get_json()["status"] == "ok"


def test_items_lifecycle(client):
    get_res = client.get("/api/items")
    assert get_res.status_code == 200

    post_res = client.post("/api/items", json={"name": "Sample Task"})
    assert post_res.status_code == 201
    assert post_res.get_json()["name"] == "Sample Task"
