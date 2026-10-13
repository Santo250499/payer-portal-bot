"""Build a static, click-through copy of the mock portal for GitHub Pages.

GitHub Pages can't run Flask, so this renders the real Jinja templates once per
screen and adds a small script that handles sign-in and search in the browser.
Usage:  python scripts/build_static.py site/
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from portal.app import CLAIMS, USERS, app  # noqa: E402

DEMO_USER, DEMO_PASS = next(iter(USERS.items()))
out = Path(sys.argv[1] if len(sys.argv) > 1 else "site")
out.mkdir(parents=True, exist_ok=True)
shutil.copy(ROOT / "portal/static/portal.css", out / "portal.css")

HINT = (f'<p class="demo-hint">Demo sign-in: <b>{DEMO_USER}</b> / <b>{DEMO_PASS}</b>. '
        'This is a static preview; all claims are synthetic.</p>')

SHIM = """<script>
(() => {
  const CLAIMS = %s, USER = %s, PASS = %s;
  const login = document.querySelector('.login-form');
  if (login) login.addEventListener('submit', e => {
    e.preventDefault();
    const ok = document.getElementById('username').value === USER && document.getElementById('password').value === PASS;
    location.href = ok ? 'claims.html' : 'login-error.html';
  });
  const search = document.querySelector('.search');
  if (search) search.addEventListener('submit', e => {
    e.preventDefault();
    const id = document.getElementById('claim-id').value.trim().toUpperCase();
    location.href = CLAIMS.includes(id) ? 'claim-' + id + '.html' : 'not-found.html?id=' + encodeURIComponent(id);
  });
  const nf = document.getElementById('not-found');
  if (nf) {
    const id = new URLSearchParams(location.search).get('id') || '';
    nf.querySelector('h2').textContent = 'No claim found for ' + id;
    document.getElementById('claim-id').value = id;
  }
})();
</script>""" % (json.dumps(list(CLAIMS)), json.dumps(DEMO_USER), json.dumps(DEMO_PASS))


def page(template, name, **ctx):
    with app.test_request_context():
        html = app.jinja_env.get_template(template).render(**ctx)
    html = (html.replace("/static/portal.css", "portal.css")
                .replace('href="/logout"', 'href="index.html"')
                .replace('href="/claims"', 'href="claims.html"')
                .replace("</body>", SHIM + "\n</body>"))
    if template == "login.html":
        html = html.replace('<p class="sub">Use your biller account to continue.</p>',
                            '<p class="sub">Use your biller account to continue.</p>' + HINT)
    (out / name).write_text(html, encoding="utf-8")


common = dict(user=DEMO_USER, samples=list(CLAIMS))
page("login.html", "index.html", error=None)
page("login.html", "login-error.html", error="Invalid username or password")
page("claims.html", "claims.html", claim_id=None, result=None, **common)
for cid, res in CLAIMS.items():
    page("claims.html", f"claim-{cid}.html", claim_id=cid, result=res, **common)
page("claims.html", "not-found.html", claim_id="CLM-0000", result=None, **common)
page("unavailable.html", "unavailable.html")
(out / ".nojekyll").write_text("")
print(f"Built {len(list(out.glob('*.html')))} pages into {out}/")
