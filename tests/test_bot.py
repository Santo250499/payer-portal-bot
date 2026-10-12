"""Tests: unit test for CSV reading + an end-to-end run against the real mock portal."""
import csv
import sqlite3
import threading

import pytest
from werkzeug.serving import make_server

from bot import run_bot
from portal.app import app


@pytest.fixture(scope="module")
def portal():
    srv = make_server("127.0.0.1", 5055, app)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield "http://127.0.0.1:5055"
    srv.shutdown()


@pytest.fixture
def env(portal, monkeypatch, tmp_path):
    monkeypatch.setattr(run_bot, "PORTAL_URL", portal)
    monkeypatch.setattr(run_bot, "SHOT_DIR", tmp_path / "shots")
    monkeypatch.setenv("PORTAL_USER", "demo_biller")
    monkeypatch.setenv("PORTAL_PASS", "S3cure!pass")
    return tmp_path


def test_read_claim_ids(tmp_path):
    p = tmp_path / "c.csv"
    p.write_text("claim_id\nCLM-1\n\nCLM-2\n")
    assert run_bot.read_claim_ids(str(p)) == ["CLM-1", "CLM-2"]


def test_portal_login_required():
    c = app.test_client()
    assert c.get("/claims").status_code == 302
    assert b"Invalid" in c.post("/", data={"username": "x", "password": "y"}).data


def test_end_to_end(env):
    out, db = env / "r.csv", env / "r.db"
    results = run_bot.run("data/claims.csv", str(out), str(db))
    by_id = {r["claim_id"]: r["status"] for r in results}
    assert by_id["CLM-2001"] == "Paid" and by_id["CLM-2002"] == "Denied"
    assert by_id["CLM-9999"] == "NOT_FOUND"
    assert len(list(csv.DictReader(open(out)))) == 6
    assert sqlite3.connect(db).execute("SELECT count(*) FROM claim_status").fetchone()[0] == 6


def test_bad_credentials(env, monkeypatch):
    monkeypatch.setenv("PORTAL_PASS", "wrong")
    with pytest.raises(RuntimeError, match="Login failed"):
        run_bot.run("data/claims.csv", str(env / "r.csv"), str(env / "r.db"))
    assert (env / "shots" / "fatal.png").exists()


def test_retry_and_screenshot_on_flaky_portal(env, monkeypatch):
    calls = {"n": 0}
    real = run_bot.lookup

    def flaky(page, cid):  # fail the first attempt, then succeed
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated timeout")
        return real(page, cid)

    monkeypatch.setattr(run_bot, "lookup", flaky)
    p = env / "one.csv"
    p.write_text("claim_id\nCLM-2003\n")
    r = run_bot.run(str(p), str(env / "r.csv"), str(env / "r.db"))[0]
    assert r["status"] == "Pending" and r["attempts"] == 2
    assert (env / "shots" / "CLM-2003_attempt1.png").exists()
