"""The four pictures for the project page, each showing a provider getting something.

Not infrastructure, not a diagram: the contradicted draft, the question that settles it, the receipt
filed with the meal, and the audit that found the stale rule. Shot against a running server with
state already in it (ask the yogurt question first), at 1280 wide, light theme.

    python tools/gallery_shots.py http://localhost:8011 submission-images/prove
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


def main(base: str, out: str) -> int:
    outdir = Path(out)
    outdir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1280, "height": 900}, device_scale_factor=2)
        pg.add_init_script("try{localStorage.setItem('tally-theme','light')}catch(e){}")

        pg.goto(f"{base}/app.html#ask", wait_until="networkidle")
        pg.wait_for_selector(".proof", timeout=20000)
        ask = pg.locator("#ask")
        ask.screenshot(path=str(outdir / "1-ask-and-proofs.png"))
        pg.locator(".proof").first.screenshot(path=str(outdir / "2-proof-card.png"))

        pg.goto(f"{base}/sponsor.html", wait_until="networkidle")
        pg.wait_for_timeout(1500)
        pg.screenshot(path=str(outdir / "3-sponsor-month.png"), full_page=False)

        pg.goto(f"{base}/prove.html", wait_until="networkidle")
        pg.wait_for_timeout(500)
        pg.screenshot(path=str(outdir / "4-prove-your-agent.png"), full_page=False)

        pg.goto(f"{base}/", wait_until="networkidle")
        pg.locator("#proof").screenshot(path=str(outdir / "5-before-after.png"))
        b.close()
    for f in sorted(outdir.glob("*.png")):
        print(f"  {f.name}  {f.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8011",
                  sys.argv[2] if len(sys.argv) > 2 else "submission-images/prove"))
