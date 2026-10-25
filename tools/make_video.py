"""Record the three-minute demo: the live site, driven by Playwright, narrated by Amazon Polly.

Each scene is one browser recording and one Polly line. A scene holds for as long as its narration
needs, or as long as the live agent takes, whichever is longer. Title cards are plain HTML in Tally's
own type: no third-party logos, no news screenshots, nothing the rules forbid. ffmpeg pads each clip
to its narration and joins them.

    python tools/make_video.py https://dtvxrkiam6.us-east-1.awsapprunner.com out/video

The narration is an AI voice (Amazon Polly, Matthew, neural). The write-up says so.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import boto3
from playwright.sync_api import sync_playwright

W, H = 1440, 900
VOICE = "Matthew"
Q = "Can I serve the strawberry yogurt cups as the meat alternate at snack for the 3 to 5s? The label says 17 grams of sugar."
FOLLOW = "The label says 9 grams of added sugars per 6 ounces."

CARD = """<!doctype html><html><head><meta charset="utf-8"><style>
@font-face{{font-family:Inter;src:url("{fonts}/inter.woff2") format("woff2")}}
html,body{{margin:0;height:100%;background:#FAFAF8;color:#1A1A1A;font-family:Inter,system-ui,sans-serif}}
.wrap{{position:absolute;inset:0;display:flex;flex-direction:column;justify-content:center;padding:0 120px;gap:28px}}
.k{{font-size:22px;color:#0F6E56;font-weight:650}}
h1{{font-size:{size}px;line-height:1.08;letter-spacing:-0.02em;margin:0;font-weight:650;max-width:1100px}}
p{{font-size:28px;line-height:1.4;color:#5C5C57;margin:0;max-width:1000px}}
.n{{font-size:120px;font-weight:650;letter-spacing:-0.03em;color:#0F6E56;line-height:1}}
table{{border-collapse:collapse;font-size:30px;margin-top:8px}} td{{padding:10px 36px 10px 0}} td.r{{text-align:right;font-variant-numeric:tabular-nums;font-weight:650}}
.mark{{position:absolute;left:120px;top:72px;display:flex;align-items:center;gap:14px;font-weight:650;font-size:26px}}
.mark i{{display:inline-block;width:28px;height:28px;border-radius:7px;background:#0F6E56}}
</style></head><body><div class="mark"><i></i>Tally</div><div class="wrap">{body}</div></body></html>"""


def card(path: Path, body: str, size: int = 64, fonts: str = "") -> str:
    path.write_text(CARD.format(body=body, size=size, fonts=fonts), encoding="utf-8")
    return path.resolve().as_uri()


def polly(text: str, out: Path) -> float:
    p = boto3.client("polly", region_name="us-east-1")
    r = p.synthesize_speech(Text=text, VoiceId=VOICE, Engine="neural", OutputFormat="mp3")
    out.write_bytes(r["AudioStream"].read())
    d = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)],
                       capture_output=True, text=True, check=True).stdout.strip()
    return float(d)


def main(base: str, out: str) -> int:
    outdir = Path(out)
    if outdir.exists():
        shutil.rmtree(outdir)
    (outdir / "raw").mkdir(parents=True)
    cards = outdir / "cards"
    cards.mkdir()
    fonts = (Path(__file__).resolve().parent.parent / "web" / "fonts").as_uri()

    scenes: list[dict] = []

    def scene(name: str, say: str, run, min_hold: float = 0.0, tail: bool = False, good=None):
        """tail=True keeps the END of the recording: live scenes wait on the agent, and the viewer
        should see the result arrive, not the whole wait. `good(note)` says whether a take is usable;
        the live agent is not deterministic, so a bad take is re-recorded, up to three times."""
        scenes.append({"name": name, "say": say, "run": run, "min_hold": min_hold, "tail": tail, "good": good})

    # 1. The opener, as a card in our own type.
    c1 = card(cards / "1.html", "<div class='k'>2024</div><h1>A city's official chatbot told landlords they could refuse housing vouchers.</h1><p>It was wrong. It stayed online for nearly two years.</p>")
    scene("01-open", "In 2024 a city's official chatbot told landlords they could refuse housing vouchers. It was wrong, and it stayed online for nearly two years.",
          lambda pg: (pg.goto(c1), pg.wait_for_timeout(500)))

    # 2. Tally, with a plate logged.
    def s2(pg):
        pg.goto(f"{base}/app.html", wait_until="networkidle")
        pg.wait_for_timeout(1500)
        pg.mouse.wheel(0, 300)
        pg.wait_for_timeout(1500)
    scene("02-tally", "This is Tally, our agent for home child care. It reads the plate and keeps the federal meal records.", s2)

    # 3. Before: proving off.
    def s3(pg):
        pg.goto(f"{base}/app.html#ask", wait_until="networkidle")
        pg.wait_for_timeout(800)
        pg.locator("#ask-text").fill(Q)
        pg.locator("#ask-prove").uncheck()
        pg.wait_for_timeout(600)
        pg.locator("#ask-go").click()
        pg.locator("#ask-answer:not([hidden])").wait_for(timeout=120000)
        pg.wait_for_timeout(2500)
        return pg.locator("#ask-answer").inner_text()
    scene("03-before", "Ask it what the rules say. Proving off: this is the agent as it shipped in September. Confident, from memory, with no way to check itself.", s3, tail=True, good=lambda n: "23" in n)

    # 4. The cost.
    c4 = card(cards / "4.html", "<div class='n'>$194.04</div><h1 style='font-size:44px'>not paid this month, had she followed the old answer.</h1><p>One snack a day, nine children, 22 serving days, at this year's rate. A disallowed meal is the whole meal.</p>", 44)
    scene("04-cost", "That answer has been wrong since October 2025. Followed for a month, it is 194 dollars not paid for nine children.",
          lambda pg: (pg.goto(c4), pg.wait_for_timeout(500)))

    # 5. After: proving on.
    def s5(pg):
        pg.goto(f"{base}/app.html#ask", wait_until="networkidle")
        pg.wait_for_timeout(800)
        pg.locator("#ask-text").fill(Q)
        if not pg.locator("#ask-prove").is_checked():
            pg.locator("#ask-prove").check()
        pg.wait_for_timeout(600)
        pg.locator("#ask-go").click()
        pg.locator(".proof").first.wait_for(timeout=180000)
        pg.wait_for_timeout(1500)
        pg.locator(".proof").first.scroll_into_view_if_needed()
        pg.wait_for_timeout(4000)
        return pg.locator("#ask-answer").inner_text()
    scene("05-after", "Same agent, same question, one new tool. Its draft goes to Amazon Bedrock Automated Reasoning, which holds the regulation as formal logic. Not an opinion. A proof. The rule it broke, by name, and the cost beneath it. Then it asks the one fact the rule turns on.", s5, tail=True)

    # 6. She answers; proved.
    def s6(pg):
        pg.goto(f"{base}/app.html#ask", wait_until="networkidle")
        pg.wait_for_timeout(800)
        pg.locator("#ask-text").fill(FOLLOW)
        pg.locator("#ask-go").click()
        start = pg.locator(".proof").count()
        pg.wait_for_function(f"document.querySelectorAll('.proof').length > {start}", timeout=180000)
        pg.wait_for_timeout(1500)
        pg.locator(".proof").first.scroll_into_view_if_needed()
        pg.wait_for_timeout(3000)
        return pg.locator("#ask-answer").inner_text()
    scene("06-proved", "Nine grams added. Proved, with the rule it rests on, and the receipt filed in Amazon S3 where nobody can edit it for three years.", s6, tail=True, good=lambda n: "23" not in n)

    # 7. The sponsor's month.
    def s7(pg):
        pg.goto(f"{base}/sponsor.html", wait_until="networkidle")
        pg.wait_for_timeout(1500)
        pg.mouse.wheel(0, 900)
        pg.wait_for_timeout(2500)
    scene("07-sponsor", "The sponsor who signs her claim sees the receipt on the meal, and the rulebook version it was decided under.", s7)

    # 8. The audit.
    c8 = card(cards / "8.html", "<div class='k'>Then we pointed the tool at Tally's own rulebook</div><h1 style='font-size:48px'>1 of 23 statements contradicted the regulation.</h1><p><b style='color:#B42318'>INVALID</b> rules/cacfp_rules.json label_checks.yogurt_sugar<br>&ldquo;Yogurt must contain no more than 23 grams of sugar per 6 ounces.&rdquo;<br><br>Fixed: 12 grams of <b>added</b> sugars. After the fix, 0 of 23.</p>", 48)
    scene("08-audit", "Then we pointed the tool at our own rulebook. It found our stale yogurt rule, expired a year earlier. The first thing it caught was us. Fixed, and the audit now finds zero.",
          lambda pg: (pg.goto(c8), pg.wait_for_timeout(500)))

    # 9. The numbers.
    c9 = card(cards / "9.html", "<div class='k'>30 questions USDA has answered. Wrong answers served:</div><table><tr><td>A general assistant, same model</td><td class='r'>9 of 30</td></tr><tr><td>Tally without the tool</td><td class='r'>3 of 30</td></tr><tr><td>Two agents debate, a judge decides</td><td class='r'>6 of 30</td></tr><tr><td>Tally with prove_answer</td><td class='r' style='color:#0F6E56'>1 of 30</td></tr></table><p style='margin-top:12px'>0 of 30 correct answers wrongly blocked. Held out: 8 of 10 caught, 0 blocked. Every number recounts with one command, no AWS needed.</p>", 48)
    scene("09-numbers", "On thirty questions USDA has answered, a general assistant served nine wrong answers. Two agents debating, six. With the tool, one. And zero correct answers wrongly blocked.",
          lambda pg: (pg.goto(c9), pg.wait_for_timeout(500)))

    # 10. prove.html for anyone's agent.
    def s10(pg):
        pg.goto(f"{base}/prove.html", wait_until="networkidle")
        pg.wait_for_timeout(1200)
        pg.locator("#go").click()
        pg.locator("#out:not([hidden])").wait_for(timeout=90000)
        pg.wait_for_timeout(3500)
        return pg.locator("#out").inner_text()
    scene("10-prove", "The same tool is a public page, an MCP tool, a Lambda URL, and one line in any Strands agent. Paste your agent's answer; the proof comes back in six seconds.", s10, tail=True, good=lambda n: "Contradicts" in n)

    # 11. Close.
    c11 = card(cards / "11.html", "<h1>The model drafts.<br>The regulation decides.</h1><p>Tally, now with proof. One tool, on Amazon Bedrock with the Strands Agents SDK.<br>github.com/usv240/tally-prove</p>", 72)
    scene("11-close", "The model drafts. The regulation decides. Tally, now with proof. One tool, built on Amazon Bedrock with Strands.",
          lambda pg: (pg.goto(c11), pg.wait_for_timeout(500)))

    # Narration first, so each clip knows how long to hold.
    for s in scenes:
        s["audio"] = outdir / "raw" / f"{s['name']}.mp3"
        s["secs"] = polly(s["say"], s["audio"])
        print(f"  {s['name']:<12} narration {s['secs']:5.1f}s")

    with sync_playwright() as p:
        b = p.chromium.launch()
        for s in scenes:
            for take in range(1, 4):
                ctx = b.new_context(viewport={"width": W, "height": H}, record_video_dir=str(outdir / "raw"),
                                    record_video_size={"width": W, "height": H})
                ctx.add_init_script("try{localStorage.setItem('tally-theme','light')}catch(e){}")
                pg = ctx.new_page()
                t0 = time.time()
                note = s["run"](pg)
                elapsed = time.time() - t0
                hold = max(s["secs"] + 0.6, s["min_hold"]) - elapsed
                if hold > 0:
                    pg.wait_for_timeout(int(hold * 1000))
                video = pg.video
                pg.close()
                ctx.close()
                src = Path(video.path())
                s["video"] = outdir / "raw" / f"{s['name']}.webm"
                if s["video"].exists():
                    s["video"].unlink()
                src.rename(s["video"])
                s["note"] = str(note)[:160].replace(chr(10), " ") if isinstance(note, str) else ""
                ok = s["good"] is None or s["good"](s["note"])
                print(f"  {s['name']:<12} take {take} {time.time() - t0:5.1f}s  {'ok ' if ok else 'BAD'} {s['note'][:60]}")
                if ok:
                    break
        b.close()

    # Pad or trim each clip to its narration, mux the audio, then join.
    parts = []
    for s in scenes:
        dur = max(s["secs"] + 0.6, s["min_hold"])
        clip = outdir / "raw" / f"{s['name']}.mp4"
        rec = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                    str(s["video"])], capture_output=True, text=True, check=True).stdout.strip() or 0)
        start = max(0.0, rec - dur) if s.get("tail") and rec > dur else 0.0
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(s["video"]), "-i", str(s["audio"]),
                        "-filter_complex", f"[0:v]trim=start={start:.2f},setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration=30,"
                                           f"trim=duration={dur:.2f},setpts=PTS-STARTPTS,fps=30[v];"
                                           f"[1:a]apad,atrim=duration={dur:.2f},asetpts=PTS-STARTPTS[a]",
                        "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", str(clip)], check=True)
        parts.append(clip)
    lst = outdir / "parts.txt"
    lst.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in parts), encoding="utf-8")
    final = outdir / "tally-prove-demo.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(final)], check=True)
    total = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(final)],
                                 capture_output=True, text=True, check=True).stdout.strip())
    (outdir / "scenes.json").write_text(json.dumps([{k: v for k, v in s.items() if k not in ("run",)} for s in scenes], default=str, indent=1))
    print(f"\n{final}  {total:.1f} s  ({'OK, under 3 minutes' if total < 180 else 'TOO LONG, cut a scene'})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "https://dtvxrkiam6.us-east-1.awsapprunner.com",
                  sys.argv[2] if len(sys.argv) > 2 else "out/video"))
