"""Playwright RPA bot: log in to the payer portal and check claim statuses.

Steps (same as a human biller would do):
  1. Read claim IDs from an input CSV
  2. Open the portal and log in (credentials from env vars, never hard-coded)
  3. For each claim: search, read the status from the page
     - retry up to MAX_RETRIES with backoff on errors
     - save a screenshot whenever an attempt fails
  4. Write results to an output CSV and a SQLite table
"""
import csv
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

PORTAL_URL = os.getenv("PORTAL_URL", "http://127.0.0.1:5001")
MAX_RETRIES = int(os.getenv("BOT_MAX_RETRIES", "3"))
SHOT_DIR = Path(os.getenv("BOT_SCREENSHOT_DIR", "screenshots"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.StreamHandler(), logging.FileHandler("bot.log")])
log = logging.getLogger("bot")


def read_claim_ids(path: str) -> list[str]:
    with open(path, newline="") as f:
        return [row["claim_id"].strip() for row in csv.DictReader(f) if row.get("claim_id", "").strip()]


def login(page: Page, user: str, password: str):
    page.goto(PORTAL_URL)
    page.fill("#username", user)
    page.fill("#password", password)
    page.click("#login-btn")
    if page.locator("#error").count():  # login failed: stop, don't keep retrying bad creds
        raise RuntimeError("Login failed - check PORTAL_USER / PORTAL_PASS")
    page.wait_for_selector("#claim-id")
    log.info("Logged in to portal")


def lookup(page: Page, claim_id: str) -> dict:
    """One attempt to look up a claim. Raises on any page error."""
    page.goto(f"{PORTAL_URL}/claims")
    page.fill("#claim-id", claim_id)
    with page.expect_response(lambda r: r.url.endswith("/claims") and r.request.method == "POST") as resp:
        page.click("#search-btn")
    if resp.value.status >= 500:
        raise RuntimeError(f"portal returned HTTP {resp.value.status}")
    page.wait_for_selector("#result, #not-found", timeout=5000)
    if page.locator("#not-found").count():
        return {"claim_id": claim_id, "status": "NOT_FOUND"}
    text = lambda sel: page.inner_text(sel).strip()
    return {"claim_id": claim_id, "status": text("#r-status"), "billed": text("#r-amount"),
            "paid": text("#r-paid"), "date": text("#r-date"), "reason": text("#r-reason")}


def lookup_with_retry(page: Page, claim_id: str) -> dict:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return lookup(page, claim_id) | {"attempts": attempt}
        except Exception as e:
            SHOT_DIR.mkdir(exist_ok=True)
            shot = SHOT_DIR / f"{claim_id}_attempt{attempt}.png"
            page.screenshot(path=str(shot))
            log.warning("%s attempt %d failed: %s (screenshot %s)", claim_id, attempt, e, shot)
            time.sleep(0.5 * 2 ** (attempt - 1))  # exponential backoff: 0.5s, 1s, 2s
    return {"claim_id": claim_id, "status": "ERROR", "attempts": MAX_RETRIES}


FIELDS = ["claim_id", "status", "billed", "paid", "date", "reason", "attempts", "checked_at"]


def save(results: list[dict], csv_path: str, db_path: str):
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows({k: r.get(k, "") for k in FIELDS} for r in results)
    conn = sqlite3.connect(db_path)
    conn.execute(f"CREATE TABLE IF NOT EXISTS claim_status ({', '.join(FIELDS)})")
    conn.executemany(f"INSERT INTO claim_status VALUES ({','.join('?' * len(FIELDS))})",
                     [tuple(r.get(k, "") for k in FIELDS) for r in results])
    conn.commit()
    conn.close()


def run(input_csv="data/claims.csv", output_csv="output/results.csv", db_path="output/results.db",
        headless=True) -> list[dict]:
    user, password = os.environ.get("PORTAL_USER"), os.environ.get("PORTAL_PASS")
    if not user or not password:
        raise SystemExit("Set PORTAL_USER and PORTAL_PASS environment variables")
    Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    claim_ids = read_claim_ids(input_csv)
    log.info("Loaded %d claim ids from %s", len(claim_ids), input_csv)

    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        try:
            login(page, user, password)
            for cid in claim_ids:
                r = lookup_with_retry(page, cid)
                r["checked_at"] = datetime.now().isoformat(timespec="seconds")
                log.info("%s -> %s", cid, r["status"])
                results.append(r)
            page.screenshot(path="docs/last_page.png")
        except Exception:
            SHOT_DIR.mkdir(exist_ok=True)
            page.screenshot(path=str(SHOT_DIR / "fatal.png"))
            log.exception("Bot stopped with a fatal error")
            raise
        finally:
            browser.close()
    save(results, output_csv, db_path)
    log.info("Done: %d claims written to %s and %s", len(results), output_csv, db_path)
    return results


if __name__ == "__main__":
    run(*sys.argv[1:2])
