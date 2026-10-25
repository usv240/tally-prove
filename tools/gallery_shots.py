"""The four pictures for the project page, each showing a provider getting something.

Not infrastructure, not a diagram: the contradicted draft, the question that settles it, the receipt
filed with the meal, and the audit that found the stale rule. Shot against a running server with
state already in it (ask the yogurt question first), at 1280 wide, light theme.

    python tools/gallery_shots.py http://localhost:8011 submission-images/prove
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

QUESTION = ("Can I serve the strawberry yogurt cups as the meat alternate at snack for the 3 to 5s? "
            "The label says 17 grams of sugar.")


def post(base: str, path: str, body: dict, headers: dict | None = None) -> dict:
    req = urllib.request.Request(f"{base}{path}", data=json.dumps(body).encode(), method="POST",
                                 headers={"content-type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read() or b"{}")


def main(base: str, out: str) -> int:
    outdir = Path(out)
    outdir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1280, "height": 900}, device_scale_factor=2)
        pg.add_init_script("try{localStorage.setItem('tally-theme','light')}catch(e){}")

        # The cover needs the contradiction with the dollar figure. The agent's first draft is not
        # always contradicted (it often asks for the fact instead), so the wrong answer is proved
        # directly through the tool's HTTP route, which is deterministic, on a fresh day.
        pg.goto(f"{base}/app.html#ask", wait_until="networkidle")
        pg.wait_for_timeout(800)
        if not pg.locator(".proof").filter(has_text="contradicts").count():
            post(base, "/api/reset", {})
            for step in ("roll", "breakfast"):
                post(base, "/api/step", {"step": step})
            key = post(base, "/api/keys", {})
            wrong = "Yes. Yogurt credits as a meat alternate and 17 grams is under the 23 gram limit."
            facts = ("The meal is a snack. The children are 3 to 5 years old. The yogurt has 17 grams of added "
                     "sugars per 6 ounces.")
            post(base, "/api/prove", {"question": QUESTION, "answer": wrong, "facts": facts},
                 headers={"x-api-key": key.get("key") or key.get("api_key") or ""})
            pg.goto(f"{base}/app.html#ask", wait_until="networkidle")
            pg.wait_for_timeout(800)
        pg.wait_for_selector(".proof", timeout=20000)
        ask = pg.locator("#ask")
        ask.screenshot(path=str(outdir / "1-ask-and-proofs.png"))
        # The cover is the contradiction with the dollar figure, whichever card happens to be newest.
        hit = pg.locator(".proof").filter(has_text="CONTRADICTS")
        (hit.first if hit.count() else pg.locator(".proof").first).screenshot(path=str(outdir / "2-proof-card.png"))

        pg.goto(f"{base}/sponsor.html", wait_until="networkidle")
        pg.wait_for_timeout(1500)
        pg.screenshot(path=str(outdir / "3-sponsor-month.png"), full_page=False)

        pg.goto(f"{base}/prove.html", wait_until="networkidle")
        pg.wait_for_timeout(500)
        pg.screenshot(path=str(outdir / "4-prove-your-agent.png"), full_page=False)

        pg.goto(f"{base}/", wait_until="networkidle")
        # The sticky header would sit over the band's heading in an element capture.
        pg.locator("#proof").screenshot(path=str(outdir / "5-before-after.png"),
                                         style="header { visibility: hidden !important; }")

        # The September agent's answer with the number it remembered marked in red. The agent is
        # not deterministic, so this takes the first of a few tries that quotes the old limit.
        for _ in range(4):
            pg.goto(f"{base}/app.html#ask", wait_until="networkidle")
            pg.locator("#ask-text").fill(QUESTION)
            pg.locator("#ask-prove").uncheck()
            pg.locator("#ask-go").click()
            pg.locator("#ask-answer:not([hidden])").wait_for(timeout=120000)
            if "From nowhere" in pg.locator("#ask-answer").inner_text():
                pg.locator("#ask-answer").screenshot(path=str(outdir / "6-before-from-nowhere.png"))
                break
        b.close()
    for f in sorted(outdir.glob("*.png")):
        print(f"  {f.name}  {f.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8011",
                  sys.argv[2] if len(sys.argv) > 2 else "submission-images/prove"))
