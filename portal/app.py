"""A tiny MOCK payer portal (think Availity / a payer website) for the bot to practise on.

Login page -> claim status search page. All claims are fake.
Set PORTAL_FLAKY=1 to make every 3rd lookup fail with a 500, so retries can be shown.
"""
import os

from flask import Flask, redirect, render_template, request, session, url_for

app = Flask(__name__)
app.secret_key = os.getenv("PORTAL_SECRET", "mock-portal-secret")

USERS = {os.getenv("PORTAL_USER", "demo_biller"): os.getenv("PORTAL_PASS", "S3cure!pass")}

CLAIMS = {  # synthetic claim data
    "CLM-2001": {"status": "Paid", "amount": "$1,250.00", "paid": "$980.00", "date": "2026-09-14"},
    "CLM-2002": {"status": "Denied", "amount": "$310.50", "paid": "$0.00", "date": "2026-09-20", "reason": "CARC 16 - missing info"},
    "CLM-2003": {"status": "Pending", "amount": "$88.00", "paid": "$0.00", "date": "2026-10-01"},
    "CLM-2004": {"status": "In Review", "amount": "$4,020.00", "paid": "$0.00", "date": "2026-10-03"},
    "CLM-2005": {"status": "Denied", "amount": "$725.00", "paid": "$0.00", "date": "2026-10-05", "reason": "CARC 197 - no auth"},
}

LOOKUPS = {"n": 0}  # request counter for flaky mode


@app.route("/", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        u, p = request.form.get("username"), request.form.get("password")
        if USERS.get(u) == p:
            session["user"] = u
            return redirect(url_for("claims"))
        error = "Invalid username or password"
    return render_template("login.html", error=error)


@app.route("/claims", methods=["GET", "POST"])
def claims():
    if "user" not in session:
        return redirect(url_for("login"))
    claim_id, result = None, None
    if request.method == "POST":
        LOOKUPS["n"] += 1
        if os.getenv("PORTAL_FLAKY") == "1" and LOOKUPS["n"] % 3 == 0:
            return render_template("unavailable.html"), 500
        claim_id = request.form.get("claim_id", "").strip().upper()
        result = CLAIMS.get(claim_id)
    return render_template("claims.html", claim_id=claim_id, result=result,
                           user=session["user"], samples=list(CLAIMS))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(port=int(os.getenv("PORTAL_PORT", 5001)))
