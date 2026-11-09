"""
The backend is a standalone API: it reads nothing outside backend/, serves no
files, and answers browsers only from the frontend origins it is told about.
None of these tests touch the database.
Run:  cd backend && python3 -m pytest tests/ -q
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

from app.config import BASE, settings
from app.main import app

client = TestClient(app)          # no `with`: startup (db, scheduler) does not run
ALLOWED = settings.ALLOW_ORIGINS[0]


def test_default_paths_stay_inside_backend():
    assert BASE.name == "backend"
    for p in (settings.KNOWLEDGE_PATH, settings.STATS_PATH):
        assert pathlib.Path(p).resolve().is_relative_to(BASE), p


def test_root_describes_the_api():
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["service"] == "Corpus Explorer API"


def test_unknown_api_route_is_json_404():
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")


@pytest.mark.parametrize("path", [
    "/..%2f..%2fREADME.md", "/%2e%2e/%2e%2e/README.md", "/..%2f..%2f.env",
    "/..%2f..%2f..%2f..%2fetc%2fpasswd", "/index.html", "/assets/app.js",
])
def test_serves_no_files(path):
    assert client.get(path).status_code == 404


def test_cors_allows_the_frontend_origin():
    r = client.options("/api/search", headers={
        "Origin": ALLOWED, "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type"})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == ALLOWED


def test_cors_refuses_other_origins():
    if "*" in settings.ALLOW_ORIGINS:
        pytest.skip("ALLOW_ORIGINS is *")
    r = client.options("/api/search", headers={
        "Origin": "https://not-the-frontend.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in r.headers


def test_cors_never_allows_writes():
    r = client.options("/api/search", headers={
        "Origin": ALLOWED, "Access-Control-Request-Method": "DELETE"})
    assert r.status_code == 400
