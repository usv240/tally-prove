"""Record the demo: the live site, driven by Playwright, narrated by Amazon Polly.

Each scene is one browser recording and one Polly line. A scene holds for as long as its narration
needs. A live scene waits on the real agent; that wait is kept, sped up and labelled as sped up, so
the viewer sees the loop run, and the result after it plays at real speed. Title cards are plain HTML
in Tally's own type: no third-party logos, no news screenshots, nothing the rules forbid. ffmpeg fits
each clip to its narration and joins them.

    python tools/make_video.py https://dtvxrkiam6.us-east-1.awsapprunner.com out/video
    python tools/make_video.py <base> out/video 06-after,07-proved     # re-record only these

The narration is an AI voice (Amazon Polly, Matthew, neural). The write-up says so.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import boto3
from playwright.sync_api import sync_playwright

W, H = 1440, 900
VOICE = "Matthew"
Q = "Can I serve the strawberry yogurt cups as the meat alternate at snack for the 3 to 5s? The label says 17 grams of sugar."
FOLLOW = "The label says 9 grams of added sugars per 6 ounces."
FONT = "C\\:/Windows/Fonts/segoeuib.ttf" if sys.platform == "win32" else "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

CARD = """<!doctype html><html><head><meta charset="utf-8"><style>
@font-face{{font-family:Inter;src:url("{fonts}/inter.woff2") format("woff2")}}
@font-face{{font-family:Mono;src:url("{fonts}/jetbrains-mono.woff2") format("woff2")}}
html,body{{margin:0;height:100%;background:#FAFAF8;color:#1A1A1A;font-family:Inter,system-ui,sans-serif}}
.wrap{{position:absolute;inset:0;display:flex;flex-direction:column;justify-content:center;padding:0 120px;gap:28px}}
.k{{font-size:24px;color:#0F6E56;font-weight:650}}
.k.bad{{color:#B42318}}
h1{{font-size:{size}px;line-height:1.1;letter-spacing:-0.02em;margin:0;font-weight:650;max-width:1150px}}
p{{font-size:28px;line-height:1.45;color:#5C5C57;margin:0;max-width:1080px}}
.n{{font-size:136px;font-weight:650;letter-spacing:-0.03em;color:#B42318;line-height:1;font-variant-numeric:tabular-nums}}
table{{border-collapse:collapse;font-size:32px;margin-top:4px}} td{{padding:12px 40px 12px 0;border-bottom:1px solid #E4E2DC}}
td.r{{text-align:right;font-variant-numeric:tabular-nums;font-weight:650}} tr.us td{{color:#0F6E56;font-weight:650}}
.mark{{position:absolute;left:120px;top:72px;display:flex;align-items:center;gap:14px;font-weight:650;font-size:26px}}
.mark i{{display:inline-block;width:28px;height:28px;border-radius:7px;background:#0F6E56}}
.tools{{display:grid;grid-template-columns:1fr 1fr;gap:56px;max-width:1150px}}
.tools h2{{font-size:26px;margin:0 0 14px;color:#5C5C57;font-weight:600}}
.tools ol{{margin:0;padding:0;list-style:none;display:grid;gap:10px;font:500 26px/1.3 Mono,ui-monospace,monospace}}
.tools li{{padding:10px 16px;border:1px solid #E4E2DC;border-radius:10px;background:#fff}}
.tools li.new{{border:2px solid #0F6E56;background:#E7F4EE;color:#0F6E56;font-weight:700}}
.flow{{display:flex;gap:14px;align-items:center;font-size:26px;flex-wrap:wrap}}
.flow b{{padding:8px 14px;border-radius:999px;border:2px solid currentColor;font-weight:650}}
.ok{{color:#0F6E56}} .no{{color:#B42318}} .ask{{color:#9A5B00}}
pre{{font:500 26px/1.5 Mono,ui-monospace,monospace;background:#1F2421;color:#F2F1EC;padding:28px 32px;border-radius:14px;margin:0;max-width:1100px;white-space:pre-wrap}}
pre i{{color:#8FD6B4;font-style:normal}}
</style></head><body><div class="mark"><i></i>Tally</div><div class="wrap">{body}</div></body></html>"""

# What the camera adds to a live page: larger type, so receipts read on a phone-sized YouTube player,
# a BEFORE or AFTER label that never leaves the frame, and a ring where the narration is pointing.
DEMO_CSS = """
html { zoom: 1.2; }
.demo-badge { position: fixed; left: 50%; transform: translateX(-50%); bottom: 22px; z-index: 9999;
  padding: 10px 20px; border-radius: 999px; font: 700 17px/1.2 Inter, system-ui, sans-serif;
  letter-spacing: .04em; box-shadow: 0 6px 24px rgba(0,0,0,.14); white-space: nowrap; }
.demo-badge.before { background: #FDECEA; color: #B42318; border: 2px solid #B42318; }
.demo-badge.after { background: #E7F4EE; color: #0F6E56; border: 2px solid #0F6E56; }
.demo-focus { outline: 3px solid #D9822B !important; outline-offset: 5px; border-radius: 10px;
  transition: outline-color .3s ease-out; }
"""


def card(path: Path, body: str, size: int = 64, fonts: str = "") -> str:
    path.write_text(CARD.format(body=body, size=size, fonts=fonts), encoding="utf-8")
    return path.resolve().as_uri()


def probe(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout.strip()
    return float(out or 0)


def polly(text: str, out: Path) -> float:
    p = boto3.client("polly", region_name="us-east-1")
    r = p.synthesize_speech(Text=text, VoiceId=VOICE, Engine="neural", OutputFormat="mp3")
    out.write_bytes(r["AudioStream"].read())
    return probe(out)


def dress(pg, badge: str = "") -> None:
    """Zoom the page for the camera and pin the BEFORE or AFTER label."""
    pg.add_style_tag(content=DEMO_CSS)
    if badge:
        tone, text = badge.split(":", 1)
        pg.evaluate("([t, x]) => { const b = document.createElement('div'); b.className = 'demo-badge ' + t;"
                    " b.textContent = x; document.body.appendChild(b); }", [tone, text])


def point(target, pause: int = 0) -> None:
    """Ring one element, scroll it to the middle of the frame, and drop the ring from anything else."""
    target.evaluate("e => { document.querySelectorAll('.demo-focus').forEach(x => x.classList.remove('demo-focus'));"
                    " e.classList.add('demo-focus'); e.scrollIntoView({ behavior: 'smooth', block: 'center' }); }")
    if pause:
        target.page.wait_for_timeout(pause)


def main(base: str, out: str, only: set[str] | None = None) -> int:
    outdir = Path(out)
    # `only` names scenes to re-record; every other scene reuses its narration and clip from the last
    # run, so one unlucky take does not cost a full pass against a non-deterministic agent.
    if outdir.exists() and not only:
        shutil.rmtree(outdir)
    (outdir / "raw").mkdir(parents=True, exist_ok=True)
    cards = outdir / "cards"
    cards.mkdir(exist_ok=True)
    fonts = (Path(__file__).resolve().parent.parent / "web" / "fonts").as_uri()

    scenes: list[dict] = []
    marks: dict[str, float] = {}

    def post(path: str, body: dict | None = None) -> None:
        req = urllib.request.Request(f"{base}{path}", data=json.dumps(body or {}).encode(), method="POST",
                                     headers={"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            r.read()

    def reset_day(take: int) -> None:
        """A fresh day and a fresh conversation, so a retake does not inherit the last take's proofs."""
        post("/api/reset")
        for step in ("roll", "breakfast"):
            post("/api/step", {"step": step})

    def rebuild_for_follow(take: int) -> None:
        """The proved scene answers the question the after scene asked. A retake of it alone asks it again."""
        if take > 1 or only:
            reset_day(take)
            post("/api/ask", {"text": Q, "prove": True})

    def scene(name: str, say: str, run, ramp: bool = False, good=None, prep=None, keep: float = 0.0):
        """ramp=True: the run calls arrived() when the agent's result lands. Everything before that is
        the wait, sped up into the time the narration leaves; everything after plays at real speed.
        `keep` is how many seconds of real-speed result to reserve. `good(note)` says whether a take is
        usable; the live agent is not deterministic, so a bad take is re-recorded, up to five times.
        `prep(take)` runs before the camera starts, to put the server in the state the scene assumes."""
        scenes.append({"name": name, "say": say, "run": run, "ramp": ramp, "good": good, "prep": prep, "keep": keep})

    def arrived(name: str):
        return lambda: marks.__setitem__(name, time.time())

    # 1. Who this is for, and what is at stake.
    c1 = card(cards / "1.html", "<div class='k'>Home child care, United States</div><h1>Rosa feeds nine children a day. A federal program pays for each meal, if the meal follows the rules.</h1><p>And the rules change. The yogurt rule changed in October 2025.</p>", 60, fonts)
    scene("01-open", "Rosa runs child care from her home. A federal program pays for the meals she serves, but only when each meal follows the rules. And the rules change.",
          lambda pg: (pg.goto(c1), pg.wait_for_timeout(500)))

    # 2. Tally, as it was in September, with breakfast logged.
    def s2(pg):
        pg.goto(f"{base}/app.html", wait_until="networkidle")
        dress(pg)
        pg.wait_for_timeout(1200)
        meal = pg.locator(".meal-card").first
        if meal.count():
            point(meal, 2500)
        point(pg.locator("#ask"), 2000)
    scene("02-tally", "Tally is her agent, built with Strands on Amazon Bedrock. It reads her plates, keeps the federal meal records, and answers her questions about the rules.",
          s2, prep=reset_day)

    # 3. Before: the agent as it shipped, no tool.
    def s3(pg):
        pg.goto(f"{base}/app.html#ask", wait_until="networkidle")
        dress(pg, "before:BEFORE  ·  the September agent, no new tool")
        pg.wait_for_timeout(600)
        point(pg.locator("#ask-form"))
        pg.locator("#ask-prove").uncheck()
        pg.locator("#ask-text").type(Q, delay=12)
        pg.locator("#ask-go").click()
        pg.locator("#ask-answer:not([hidden]):not(.working)").wait_for(timeout=180000)
        arrived("03-before")()
        pg.wait_for_timeout(300)
        point(pg.locator("#ask-answer"), 5500)
        nowhere = pg.locator("#ask-answer .nowhere")
        if nowhere.count():
            point(nowhere, 4000)
        return pg.locator("#ask-answer").inner_text()
    scene("03-before", "Before. She asks whether the strawberry yogurt counts at snack. The label says seventeen grams of sugar. Tally answers from memory, with a twenty-three gram limit. That limit expired a year ago. The page marks the number in red: it is in neither her words nor the regulation.",
          s3, ramp=True, keep=11.0, prep=reset_day, good=lambda n: "From nowhere: 23" in n)

    # 4. What that one answer costs.
    c4 = card(cards / "4.html", "<div class='k bad'>Had she followed that answer</div><div class='n'>$194.04</div><h1 style='font-size:44px'>not paid, in one month.</h1><p>One snack a day, nine children, 22 serving days, at this year's rate. A disallowed snack is not paid at all.</p>", 44, fonts)
    scene("04-cost", "Followed for a month, that one answer costs her a hundred and ninety four dollars, for nine children. A disallowed snack is not paid at all.",
          lambda pg: (pg.goto(c4), pg.wait_for_timeout(500)))

    # 5. Exactly one tool.
    c5 = card(cards / "5.html", "<div class='k'>The one new tool</div><div class='tools'><div><h2>September: five tools</h2><ol><li>log_plate</li><li>take_roll</li><li>record_substitution</li><li>answer_open_question</li><li>today_so_far</li></ol></div><div><h2>Now: six</h2><ol><li>log_plate</li><li>take_roll</li><li>record_substitution</li><li>answer_open_question</li><li>today_so_far</li><li class='new'>prove_answer</li></ol></div></div><div class='flow'>draft &rarr; Amazon Bedrock Automated Reasoning checks &rarr; <b class='ok'>proved</b><b class='no'>contradicted</b><b class='ask'>needs one fact</b></div>", 48, fonts)
    scene("05-tool", "So we gave Tally exactly one new tool: prove answer. Every rules answer it drafts goes to Amazon Bedrock Automated Reasoning checks, which hold the regulation as formal logic. The answer comes back proved, contradicted, or missing one fact.",
          lambda pg: (pg.goto(c5), pg.wait_for_timeout(500)))

    # 6. After: same question, the tool on. The loop is visible while it runs.
    def s6(pg):
        pg.goto(f"{base}/app.html#ask", wait_until="networkidle")
        dress(pg, "after:AFTER  ·  same agent, one new tool: prove_answer")
        pg.wait_for_timeout(600)
        point(pg.locator("#ask-form"))
        if not pg.locator("#ask-prove").is_checked():
            pg.locator("#ask-prove").check()
        pg.locator("#ask-text").type(Q, delay=12)
        start = pg.locator(".proof").count()
        pg.locator("#ask-go").click()
        pg.wait_for_timeout(400)
        point(pg.locator("#ask-answer"))
        pg.wait_for_function(f"document.querySelectorAll('.proof').length > {start}", timeout=240000)
        pg.locator("#ask-answer:not(.working)").wait_for(timeout=60000)
        arrived("06-after")()
        pg.wait_for_timeout(300)
        new = pg.locator(".proof").count() - start
        cards_text = [pg.locator(".proof").nth(i).inner_text() for i in range(new)]
        hit = pg.locator(".proof").filter(has_text="CONTRADICTS")
        rule = (hit.first if hit.count() else pg.locator(".proof").first).locator(".rule").first
        if rule.count():
            point(rule, 6000)
        point(pg.locator("#ask-answer"), 5000)
        return " // ".join(cards_text) + " || " + pg.locator("#ask-answer").inner_text()
    scene("06-after", "After. Same agent, same question. Watch the loop: draft, check, contradicted, rewrite. The receipt quotes the rule it broke: twelve grams of added sugars. And instead of guessing, Tally asks her the one fact that decides it.",
          s6, ramp=True, keep=11.5, prep=reset_day,
          good=lambda n: "CONTRADICTS" in n and ("12 grams" in n or "added sugars, not total" in n) and "?" in n.split("||")[-1])

    # 7. She answers; proved; filed.
    def s7(pg):
        pg.goto(f"{base}/app.html#ask", wait_until="networkidle")
        dress(pg, "after:AFTER  ·  same agent, one new tool: prove_answer")
        pg.wait_for_timeout(600)
        point(pg.locator("#ask-form"))
        pg.locator("#ask-text").type(FOLLOW, delay=12)
        start = pg.locator(".proof").count()
        pg.locator("#ask-go").click()
        pg.wait_for_timeout(400)
        point(pg.locator("#ask-answer"))
        pg.wait_for_function(f"document.querySelectorAll('.proof').length > {start}", timeout=240000)
        pg.locator("#ask-answer:not(.working)").wait_for(timeout=60000)
        arrived("07-proved")()
        pg.wait_for_timeout(300)
        first = pg.locator(".proof").first
        point(first, 4500)
        point(first.locator(".stamp"), 4500)
        return first.inner_text() + " || " + pg.locator("#ask-answer").inner_text()
    scene("07-proved", "She answers: nine grams added. Proved. The receipt is filed in Amazon S3 with Object Lock, so no one, including us, can change it for three years.",
          s7, ramp=True, keep=9.5, prep=rebuild_for_follow,
          good=lambda n: "PROVED" in n and "filed in S3" in n and "23" not in n.split("||")[-1])

    # 8. The first thing it caught was us.
    c8 = card(cards / "8.html", "<div class='k'>Then we pointed the tool at Tally's own rulebook</div><h1 style='font-size:52px'>1 of 23 rules contradicted the regulation. It was ours.</h1><p><b style='color:#B42318'>INVALID</b>&nbsp; label_checks.yogurt_sugar<br>&ldquo;no more than 23 grams of sugar per 6 ounces&rdquo;<br><br>Fixed to 12 grams of <b>added</b> sugars. The audit now finds 0 of 23.</p>", 52, fonts)
    scene("08-audit", "Then we pointed the tool at Tally's own rulebook. One rule in twenty three contradicted the regulation: our old yogurt limit. The first wrong answer it caught was ours.",
          lambda pg: (pg.goto(c8), pg.wait_for_timeout(500)))

    # 9. Measured.
    c9 = card(cards / "9.html", "<div class='k'>30 questions USDA has already answered. Wrong answers given:</div><table><tr><td>A general assistant, same model</td><td class='r'>9 of 30</td></tr><tr><td>Two agents debate, a judge decides</td><td class='r'>6 of 30</td></tr><tr><td>Tally without the tool</td><td class='r'>3 of 30</td></tr><tr class='us'><td>Tally with prove_answer</td><td class='r'>1 of 30</td></tr></table><p>0 of 30 correct answers blocked. 0 of 9 attacks proved. Recounts with one command, no AWS needed.</p>", 48, fonts)
    scene("09-numbers", "On thirty questions USDA has already answered, a general assistant gave nine wrong answers. Two agents debating, six. Tally with the tool, one. It blocked none of the thirty correct answers, and none of nine attacks got a wrong answer proved.",
          lambda pg: (pg.goto(c9), pg.wait_for_timeout(500)))

    # 10. Anyone's agent, on the public page.
    def s10(pg):
        pg.goto(f"{base}/prove.html", wait_until="networkidle")
        dress(pg)
        pg.wait_for_timeout(500)
        point(pg.locator("#a"), 1500)
        pg.locator("#go").click()
        pg.locator("#out:not([hidden])").wait_for(timeout=90000)
        arrived("10-prove")()
        pg.wait_for_timeout(300)
        point(pg.locator("#out"), 4500)
        return pg.locator("#out").inner_text()
    scene("10-prove", "It is not locked inside Tally. Paste any agent's answer on this public page, or call the same check as an AWS Lambda URL, or over MCP.",
          s10, ramp=True, keep=6.0, good=lambda n: "Contradicts" in n)

    # 11. Reuse in one line.
    c11 = card(cards / "11.html", "<div class='k'>Any Strands agent, one hook</div><pre><i>from</i> tally.strands_hook <i>import</i> ProveAnswers\n\nagent = Agent(tools=[...], hooks=[ProveAnswers()])</pre><p>Also an MCP server and a public Lambda URL. Compile a different rulebook into a policy and the same pattern guards it.</p>", 48, fonts)
    scene("11-reuse", "For a Strands agent, it is one hook. Compile a different rulebook into a policy, and the same pattern guards it.",
          lambda pg: (pg.goto(c11), pg.wait_for_timeout(500)))

    # 12. Close.
    c12 = card(cards / "12.html", "<h1>The model drafts.<br>The regulation decides.</h1><p>Tally, now with proof. One tool, on Amazon Bedrock with the Strands Agents SDK.<br>github.com/usv240/tally-prove</p>", 76, fonts)
    scene("12-close", "The model drafts. The regulation decides. Tally, now with proof.",
          lambda pg: (pg.goto(c12), pg.wait_for_timeout(500)))

    # Narration first, so each clip knows how long to hold.
    for s in scenes:
        s["audio"] = outdir / "raw" / f"{s['name']}.mp3"
        s["video"] = outdir / "raw" / f"{s['name']}.webm"
        meta = outdir / "raw" / f"{s['name']}.json"
        if only and s["name"] not in only and s["audio"].exists() and s["video"].exists():
            s["secs"] = probe(s["audio"])
            s["wait"] = json.loads(meta.read_text()).get("wait", 0.0) if meta.exists() else 0.0
            s["reuse"] = True
            continue
        s["secs"] = polly(s["say"], s["audio"])
        print(f"  {s['name']:<12} narration {s['secs']:5.1f}s")

    with sync_playwright() as p:
        b = p.chromium.launch()
        for s in scenes:
            if s.get("reuse"):
                continue
            for take in range(1, 6):
                if s["prep"]:
                    s["prep"](take)
                marks.pop(s["name"], None)
                ctx = b.new_context(viewport={"width": W, "height": H}, record_video_dir=str(outdir / "raw"),
                                    record_video_size={"width": W, "height": H})
                ctx.add_init_script("try{localStorage.setItem('tally-theme','light')}catch(e){}")
                pg = ctx.new_page()
                t0 = time.time()
                try:
                    note = s["run"](pg)
                except Exception as exc:  # a take the agent never finished is a bad take, not a crash
                    note = f"TIMED OUT {type(exc).__name__}: {str(exc)[:200]}"
                elapsed = time.time() - t0
                wait = (marks[s["name"]] - t0) if s["name"] in marks else 0.0
                result = elapsed - wait
                hold = (s["keep"] - result) if s["ramp"] else (s["secs"] + 0.6 - elapsed)
                if hold > 0:
                    pg.wait_for_timeout(int(hold * 1000))
                video = pg.video
                pg.close()
                ctx.close()
                src = Path(video.path())
                if s["video"].exists():
                    s["video"].unlink()
                src.rename(s["video"])
                s["wait"] = wait
                s["note"] = (str(note)[:6000].replace(chr(10), " ").encode("ascii", "replace").decode()
                             if isinstance(note, str) else "")
                (outdir / "raw" / f"{s['name']}.json").write_text(json.dumps({"wait": wait, "note": s["note"]}))
                ok = s["good"] is None or s["good"](s["note"])
                print(f"  {s['name']:<12} take {take} {time.time() - t0:5.1f}s wait {wait:5.1f}s  "
                      f"{'ok ' if ok else 'BAD'} {s['note'][:70]}")
                if ok:
                    break
            else:
                print(f"  {s['name']:<12} NO GOOD TAKE in five; the last one is in the cut. Re-record it.")
        b.close()

    # Fit each clip to its narration, mux the audio, then join.
    parts = []
    for s in scenes:
        dur = s["secs"] + 0.6
        clip = outdir / "raw" / f"{s['name']}.mp4"
        rec = probe(s["video"])
        wait = s.get("wait", 0.0)
        if s["ramp"] and wait > 0:
            # The result keeps real speed for what is left after a short, sped-up wait; the wait is
            # squeezed into the rest and labelled with how much, so nobody mistakes it for latency.
            real = min(rec - wait, max(dur - 3.0, dur * 0.6))
            room = dur - real
            speed = max(1.0, wait / room)
            label = (f",drawtext=fontfile='{FONT}':text='Sped up {speed:.0f}x while the agent works':"
                     "fontsize=26:fontcolor=white:box=1:boxcolor=0x1A1A1ACC:boxborderw=14:x=w-tw-40:y=40"
                     if speed >= 1.5 else "")
            vf = (f"[0:v]split=2[w][r];"
                  f"[w]trim=start=0:end={wait:.2f},setpts=(PTS-STARTPTS)/{speed:.4f}{label}[w2];"
                  f"[r]trim=start={wait:.2f}:end={wait + real:.2f},setpts=PTS-STARTPTS[r2];"
                  f"[w2][r2]concat=n=2:v=1:a=0,tpad=stop_mode=clone:stop_duration=30,"
                  f"trim=duration={dur:.2f},setpts=PTS-STARTPTS,fps=30[v]")
        else:
            vf = (f"[0:v]trim=start=0,setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration=30,"
                  f"trim=duration={dur:.2f},setpts=PTS-STARTPTS,fps=30[v]")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(s["video"]), "-i", str(s["audio"]),
                        "-filter_complex", vf + f";[1:a]apad,atrim=duration={dur:.2f},asetpts=PTS-STARTPTS[a]",
                        "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", str(clip)], check=True)
        parts.append(clip)
    lst = outdir / "parts.txt"
    lst.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in parts), encoding="utf-8")
    final = outdir / "tally-prove-demo.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(final)], check=True)
    total = probe(final)
    (outdir / "scenes.json").write_text(json.dumps([{k: v for k, v in s.items() if k not in ("run", "good", "prep")}
                                                    for s in scenes], default=str, indent=1))
    print(f"\n{final}  {total:.1f} s  ({'OK, under 3 minutes' if total < 180 else 'TOO LONG, cut a scene'})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "https://dtvxrkiam6.us-east-1.awsapprunner.com",
                  sys.argv[2] if len(sys.argv) > 2 else "out/video",
                  set(sys.argv[3].split(",")) if len(sys.argv) > 3 else None))
