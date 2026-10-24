/* Tally product screens. Vanilla JS against the API in tally/api.py. */

(function () {
  "use strict";

  var state = null, traceEvents = [], traceCursor = 0, busy = false;

  function api(path, opts) {
    return fetch(path, opts).then(function (r) {
      if (!r.ok) throw new Error(path + " returned " + r.status);
      return r.json();
    });
  }

  function setBusy(on, label) {
    busy = on;
    document.querySelectorAll("#steps .btn").forEach(function (b) { b.disabled = on; });
    var reset = document.getElementById("reset");
    if (reset) reset.disabled = on;
    var go = document.getElementById("ask-go");
    if (go) go.disabled = on;
    if (on && label) {
      var s = document.getElementById("status");
      s.className = "status-line";
      s.textContent = label;
    }
  }

  function photoUrl(key) {
    if (!key) return null;
    var parts = String(key).replace(/\\/g, "/").split("/");
    return "/plates/" + parts[parts.length - 1];
  }

  /* Rendering ------------------------------------------------------------ */

  function renderStatus() {
    var s = document.getElementById("status");
    s.className = "status-line " + state.tone;
    s.textContent = state.headline;
    document.getElementById("clock").textContent = window.fmtDayTime(state.now);

    var budget = state.provider.question_budget, used = state.asked_today;
    document.getElementById("quiet-text").textContent =
      "Asked you " + used + (used === 1 ? " question" : " questions") + " today. Budget " + budget + ".";
    var pips = document.getElementById("quiet-pips");
    pips.innerHTML = "";
    for (var i = 0; i < budget; i++) {
      pips.appendChild(window.h("span", { class: "pip" + (i < used ? " used" : "") }));
    }
    var r = state.ratio || {};
    document.getElementById("ratio-text").textContent = r.explanation
      ? (r.now_ok === false ? "Over your limit: " : "") + r.explanation
      : "Ratio unknown";
  }

  // Set when a control inside the step row is pressed, consumed by the next renderSteps.
  //
  // Checking document.activeElement inside renderSteps is too late: setBusy disables the pressed
  // button before the rebuild, and disabling the focused element sends focus to the body right
  // then. By the time the row is rebuilt there is nothing left to detect. So the intent is
  // recorded at the moment of the press instead.
  var returnFocusToSteps = false;

  function restoreStepFocus(host) {
    if (!returnFocusToSteps) return;
    returnFocusToSteps = false;
    var next = host.querySelector("button:not([disabled])");
    if (next) next.focus();
  }

  function renderSteps() {
    var host = document.getElementById("steps");
    // Pressing a step disables the button that was pressed and then rebuilds this whole row, and
    // either of those on its own sends focus to the body. A keyboard or screen reader user was
    // therefore returned to the top of the document after every step, and had to tab past the
    // skip link, the brand, the clock, three theme buttons and a back link to reach the next one.
    // If focus was in here when the rebuild started, it is put back on whatever is now pressable.
    // Covers the case where focus is still here, such as a render with nothing disabled.
    if (host.contains(document.activeElement)) returnFocusToSteps = true;
    host.innerHTML = "";
    var next = state.steps.filter(function (s) { return !s.done; })[0];
    state.steps.forEach(function (s) {
      // A day happens in order. Playing the evening before lunch would ask the agents to close a
      // day that has not happened, so a step that is not next is disabled and says why.
      var isNext = next && next.id === s.id;
      var b = window.h("button", {
        class: "btn" + (isNext ? " primary" : ""),
        type: "button",
        title: s.done ? "Already played" : (isNext ? s.detail : "Play the steps before this first"),
        // A disabled button's title is never announced and never rendered. The reason belongs in
        // the accessible name, which a screen reader reads even when the control is disabled.
        "aria-label": s.done ? s.title + ", already played"
          : (isNext ? null : s.title + ", not yet. Play the steps before this one first."),
        onclick: function () { returnFocusToSteps = true; runStep(s.id, s.detail); }
      }, [s.done ? "Done: " + s.title : s.title]);
      if (s.done || busy || !isNext) b.disabled = true;
      host.appendChild(b);
    });
    if (next && !playing) {
      host.appendChild(window.h("button", {
        class: "btn", type: "button", id: "play-all",
        title: "Run every remaining step, one after another",
        disabled: busy ? "" : null,
        onclick: playThrough
      }, ["Play the rest of the day"]));
    }

    var doneCount = state.steps.filter(function (s) { return s.done; }).length;
    // This demo is one shared scenario in one container, so whoever arrives next inherits the
    // state the last person left. The state they most often inherit is "finished", because both
    // the recorder and anyone pressing Play the rest run it to the end. Until this branch existed,
    // that arrival looked like a dead product: every step greyed out and reading "Done", and the
    // only way forward a small secondary Reset in the corner. The way forward has to be the most
    // prominent thing on the page, not the least.
    var shared = document.getElementById("shared-note");
    if (shared) {
      var total = state.steps.length;
      shared.hidden = false;
      shared.innerHTML = "";
      if (total > 0 && doneCount >= total) {
        shared.appendChild(window.h("span", { text:
          "Someone has already played this day through to the end, and you are seeing where "
          + "they left it. It is one shared scenario, so everyone sees the same day. " }));
        shared.appendChild(window.h("button", { class: "btn primary", type: "button",
          onclick: reset }, ["Start it again from the beginning"]));
      } else if (doneCount > 0) {
        shared.appendChild(window.h("span", { text:
          "Someone has already played " + doneCount + " of these steps. This demo is one shared "
          + "scenario, so everyone sees the same day. " }));
        shared.appendChild(window.h("button", { class: "btn small", type: "button",
          onclick: reset }, ["Start it again from the beginning"]));
      } else {
        shared.hidden = true;
      }
    }

    // The reason the later buttons are dim used to live only in a title attribute, which a
    // disabled control never shows and a touch or keyboard user never gets at all. It is said
    // here instead, in the caption that is already on the page.
    document.getElementById("step-detail").textContent = next
      ? next.detail + " Steps run in order, so the rest stay dim until this one has run."
      : "Played out. Use the button above to start it again from the beginning.";
    // Rebuilding the row above destroyed whatever was focused. Put focus back on something
    // pressable, but only if it was in here to begin with, so a render triggered by anything
    // else does not steal it.
    restoreStepFocus(host);
  }

  function chip(item) {
    var low = item.confidence < 0.75;
    return window.h("span", { class: "chip" + (low ? " low" : "") }, [
      window.h("span", { text: item.name }),
      window.h("span", { class: "comp", text: item.component.replace("_", " ") }),
      window.h("span", { class: "conf", text: Math.round(item.confidence * 100) + "%" })
    ]);
  }

  function renderMeals() {
    var host = document.getElementById("meals");
    host.innerHTML = "";
    if (!state.meals.length) {
      host.appendChild(window.h("div", { class: "card" }, [
        window.h("h3", { text: "Nothing logged yet" }),
        window.h("p", { class: "muted", style: "margin:0",
          text: "Press the first step above. Rosa says who is here, and then photographs the plate." })
      ]));
      return;
    }
    state.meals.forEach(function (m) {
      var body = window.h("div", {}, [
        window.h("div", { class: "gap-head" }, [
          window.h("span", { class: "gap-window",
            text: m.type.charAt(0).toUpperCase() + m.type.slice(1) + ", " + window.fmtTime(m.at) }),
          window.levelBadge(m.reimbursable ? "covered" : "high",
            m.reimbursable ? "will be paid" : "not reimbursable")
        ]),
        window.h("div", { class: "chips" }, m.items.map(chip))
      ]);
      if (!m.reimbursable && m.smallest_fix) {
        body.appendChild(window.h("p", { style: "margin:0 0 var(--s3);font-weight:550" },
          [m.smallest_fix, window.infoBtn("smallest_fix", "the smallest fix")]));
      }
      body.appendChild(window.h("p", { class: "small muted", style: "margin:0 0 var(--s2)" },
        [m.explanation, window.infoBtn("meal_pattern", "the meal pattern")]));
      if (m.replaces) {
        body.appendChild(window.h("p", { class: "small muted", style: "margin:0 0 var(--s2)" },
          ["This photograph replaced an earlier one, so the meal is counted once.",
           window.infoBtn("superseded", "superseded meals")]));
      }
      (m.flags || []).forEach(function (f) {
        body.appendChild(window.h("p", { class: "small muted", style: "margin:0", text: f }));
      });
      (m.label_checks || []).forEach(function (c) {
        body.appendChild(window.h("p", { class: "small", style: "margin:var(--s2) 0 0" }, [
          window.levelBadge("elevated", "check the label"), " ",
          c === "yogurt_sugar" ? "Yoghurt must be under 12g of added sugars per 6oz. A photograph cannot show that."
            : "Cereal must be under 6g of added sugars per dry ounce. A photograph cannot show that.",
          window.infoBtn("label_check", "label checks")
        ]));
      });
      body.appendChild(window.h("p", { class: "small muted", style: "margin:var(--s3) 0 0" },
        ["Logged for " + m.children_served.length + " children. Rule version " + m.rule_version + ".",
         window.infoBtn("rule_version", "the rule version")]));

      var img = photoUrl(m.photo);
      var inner = img
        ? window.h("div", { class: "meal" }, [
            window.h("img", { src: img, alt: "The " + m.type + " plate", loading: "lazy" }), body])
        : body;
      host.appendChild(window.h("div", {
        class: "card meal-card " + (m.reimbursable ? "paid" : "unpaid") }, [inner]));
    });
    window.MountInfo();
  }

  function renderSaid() {
    var host = document.getElementById("said");
    host.innerHTML = "";
    if (!state.spoken.length) {
      host.appendChild(window.h("p", { class: "muted small", text: "Nothing said yet." }));
      return;
    }
    state.spoken.forEach(function (s) {
      host.appendChild(window.h("div", { class: "said-line " + (s.tone || "info") }, [
        window.h("span", { class: "t", text: window.fmtTime(s.at) }),
        window.h("span", { text: s.text })
      ]));
    });
  }

  function renderChildren() {
    var host = document.getElementById("children");
    host.innerHTML = "";
    state.children.forEach(function (c) {
      var tags = window.h("div", { class: "child-tags" }, [
        c.present ? window.levelBadge("covered", "here")
          : c.absent ? window.levelBadge("low", "absent") : window.levelBadge("neutral", "not in yet"),
        window.h("span", { class: "badge neutral", text: "age " + c.age_group })
      ]);
      if (c.subsidized) tags.appendChild(window.h("span", { class: "badge neutral", text: "subsidised" }));
      if (c.language === "es") tags.appendChild(window.h("span", { class: "badge neutral", text: "notes in Spanish" }));
      c.allergies.forEach(function (a) {
        tags.appendChild(window.h("span", { class: "badge critical" }, [
          window.h("span", { class: "shape", "aria-hidden": "true", text: window.SHAPES.critical }),
          window.h("span", { text: a + " allergy" })
        ]));
      });
      host.appendChild(window.h("div", { class: "card child-card" }, [
        window.h("span", { class: "name", text: c.name }), tags
      ]));
    });
  }

  function questionCard(q) {
    // Prefixed, because .meal is the meal card's grid. A question about a meal used to pick
    // that up and lay itself out in two columns, stretching its buttons to the row height.
    var card = window.h("div", { class: "question q-" + q.priority }, [
      window.h("div", { class: "q", text: q.text })
    ]);
    var opts = q.options && q.options.length ? q.options : ["Yes", "No", "Not sure"];
    var row = window.h("div", { class: "btn-row" });
    opts.forEach(function (o) {
      row.appendChild(window.h("button", { class: "btn small", type: "button",
        onclick: function () { answer(q.id, o); } }, [o]));
    });
    card.appendChild(row);
    card.appendChild(window.h("p", { class: "small muted", style: "margin:var(--s3) 0 0" }, [
      q.priority === "safety" ? "A safety question. It goes through immediately and never spends the budget."
        : q.priority === "meal" ? "Asked at the table, because the answer is only useful while the food is there."
        : "Held for the evening, so it does not interrupt her day.",
      window.infoBtn("question_budget", "the question budget")
    ]));
    return card;
  }

  function renderEvening() {
    var host = document.getElementById("evening");
    host.innerHTML = "";

    var open = state.questions.filter(function (q) { return !q.answered; });
    var qcard = window.h("div", { class: "card stack" }, [
      window.h("h3", {}, ["Questions", window.infoBtn("agent_gate", "the Provider Gate")])]);
    if (!open.length) {
      // "Nothing needs her" is a real and deliberate outcome once the evening digest has closed the
      // day. Before that it is just an empty list, and reporting it as the goal claims a result the
      // agents have not produced yet.
      var closed = state.steps.some(function (s) { return s.id === "evening" && s.done; });
      qcard.appendChild(window.h("p", { class: "muted", style: "margin:0", text: closed
        ? "Nothing needs her. That is the goal."
        : "The day has not been closed yet. Questions appear here as the agents find things worth "
          + "her time, and the evening digest decides which two are worth asking." }));
    } else {
      open.forEach(function (q) { qcard.appendChild(questionCard(q)); });
    }

    // Questions the gate chose not to spend. Her budget is two a night, so a question it did not
    // have to ask is the same as one it got to ask about something new.
    var skipped = state.not_repeated || [];
    if (skipped.length) {
      qcard.appendChild(window.h("div", { class: "recall" }, [
        window.h("strong", { class: "small",
          text: "Not asked again, because you already answered:" })
      ].concat(skipped.map(function (s) {
        return window.h("p", { class: "small", style: "margin:4px 0 0",
          text: s.child + ", " + s.days_ago + " day" + (s.days_ago === 1 ? "" : "s")
                + " ago, you said " + s.answer + "."
                + (s.source === "agentcore_memory" ? " Held in AgentCore Memory." : "") });
      }))));
    }
    host.appendChild(qcard);

    var ncard = window.h("div", { class: "card stack" }, [
      window.h("h3", {}, ["Notes home", window.infoBtn("agent_notes", "Parent Notes")])]);
    if (!state.notes.length) {
      ncard.appendChild(window.h("p", { class: "muted", style: "margin:0",
        text: "Drafted in the evening, from what was actually logged." }));
    } else {
      state.notes.forEach(function (n) {
        ncard.appendChild(window.h("div", { class: "note-card" }, [
          window.h("strong", { text: n.name + (n.language === "es" ? " (Spanish)" : "") }),
          window.h("p", { class: "small", style: "margin:4px 0 0", text: n.text })
        ]));
      });
      ncard.appendChild(window.h("p", { class: "small muted", style: "margin:0",
        text: "Assembled from the record. Nothing here was invented." }));
    }
    host.appendChild(ncard);

    var ccard = window.h("div", { class: "card stack" }, [window.h("h3", { text: "Compliance" })]);
    state.compliance.forEach(function (c) {
      ccard.appendChild(window.h("p", { class: "small", style: "margin:0" }, [
        window.levelBadge(c.status === "overdue" ? "critical" : c.status === "due" ? "high" : "low",
          c.status),
        " " + c.label + ", due " + c.due
      ]));
    });
    host.appendChild(ccard);
    window.MountInfo();
  }

  function renderMonth() {
    var host = document.getElementById("month");
    host.innerHTML = "";
    var m = state.month || {};
    var card = window.h("div", { class: "card stack" }, [
      window.h("h3", {}, ["Claim for " + (m.month || ""),
        window.infoBtn("daily_maximum", "the daily maximum")]),
      window.h("span", { class: "money", text: "$" + (m.total || 0).toFixed(2) }),
      window.h("p", { class: "small muted", style: "margin:0" }, [
        (m.computed_in === "agentcore_code_interpreter"
          ? "Computed inside Amazon Bedrock AgentCore Code Interpreter, from the rates in force, "
            + "after the daily maximum is applied per child."
          : m.computed_in === "local_fallback"
            ? "Computed locally, because AgentCore did not answer"
              + (m.computed_reason ? " (" + m.computed_reason + ")" : "")
              + ". Same kernel either way."
            : "Computed as code from the rates in force, after the daily maximum is applied per child."),
        window.infoBtn("where_it_runs", "where it ran")])
    ]);
    var table = window.h("table", { class: "claim" }, [
      window.h("thead", {}, [window.h("tr", {}, [
        window.h("th", { text: "Meal" }), window.h("th", { class: "num", text: "Count" }),
        window.h("th", { class: "num", text: "Rate" }), window.h("th", { class: "num", text: "Amount" })])])
    ]);
    var tbody = window.h("tbody", {});
    (m.lines || []).forEach(function (l) {
      tbody.appendChild(window.h("tr", {}, [
        window.h("td", { text: l.meal_type }),
        window.h("td", { class: "num", text: String(l.count) }),
        window.h("td", { class: "num", text: "$" + l.rate.toFixed(2) }),
        window.h("td", { class: "num", text: "$" + l.amount.toFixed(2) })
      ]));
    });
    table.appendChild(tbody);
    card.appendChild(table);
    card.appendChild(window.h("div", { class: "btn-row" }, [
      window.h("a", { class: "btn", href: "sponsor.html" }, ["Review it as the sponsor would"])]));
    card.appendChild(window.h("p", { class: "small muted", style: "margin:0",
      text: "The sponsor sees every meal with the photograph it was judged from and the rulebook "
        + "version that judged it, which is what makes this claim defensible a year later." }));
    host.appendChild(card);

    if (m.not_reimbursable) {
      host.appendChild(window.h("div", { class: "card stack" }, [
        window.h("h3", {}, ["What the unpaid meals cost",
          window.infoBtn("lost_amount", "the lost amount")]),
        window.h("span", { class: "money lost", text: "$" + (m.lost_amount || 0).toFixed(2) }),
        window.h("p", { class: "small muted", style: "margin:0",
          text: m.not_reimbursable + " meal" + (m.not_reimbursable === 1 ? "" : "s")
                + " did not have every required component. This is what they would have paid." })
      ]));
    }

    host.appendChild(window.h("div", { class: "card" }, [
      window.h("h3", { text: "Send to the sponsor" }),
      window.h("p", { class: "muted small" },
        ["Nothing is sent until she reviews the month and presses send. The export includes every "
         + "photograph and the rule version each verdict was decided under."]),
      window.h("button", { class: "btn primary", type: "button", disabled: "",
        title: "Disabled in the demo, because nothing should be sent to a real sponsor" },
        ["Send to " + (state.provider.sponsor || "the sponsor")])
    ]));
    window.MountInfo();
  }

  var WORDS = {
    plate_read: "Plate read", meal_logged: "Meal logged", allergy_alert: "Allergy alert",
    question: "Question raised", question_answered: "Question answered", roll_taken: "Roll taken",
    substitution: "Substitution recorded", spoken: "Said out loud", day_closed: "Day closed",
    claim_built: "Claim built", notes_drafted: "Notes drafted",
    compliance_checked: "Compliance checked", subsidy_reconciled: "Subsidy reconciled",
    digest_built: "Digest built", evening_start: "Evening run started", evening_end: "Evening run finished",
    // The two AgentCore Memory events. Without these the trace printed the raw keys
    // answer_remembered and question_not_repeated, which is the one place the recall story is
    // visible and the one place it read like debug output.
    answer_remembered: "Answer remembered", question_not_repeated: "Question not repeated",
    // The prove_answer tool, added October 2026.
    asked: "Question asked", answer_drafted: "Answer drafted", answer_proved: "Answer checked",
    proof_limit: "Proof limit reached", proof_error: "Proof service unavailable"
  };

  /* Ask Tally -------------------------------------------------------------
     The one tool added for the Give your Agent a Tool challenge. The agent drafts, the solver
     proves or contradicts, and the receipt is kept. The page shows what was actually checked,
     read back off the store, never what the model says it checked. */

  var lastAsk = null;

  var VERDICT = {
    VALID: ["covered", "proved"],
    INVALID: ["critical", "contradicts a rule"], IMPOSSIBLE: ["critical", "contradicts a rule"],
    SATISFIABLE: ["high", "needs one fact"], AMBIGUOUS: ["high", "needs one fact"],
    UNVERIFIED: ["neutral", "outside the rulebook"],
    SKIPPED: ["low", "not checked"], UNCHECKED: ["low", "not checked"]
  };

  var EXAMPLES = [
    "Can I serve the strawberry yogurt cups as the meat alternate at snack for the 3 to 5s? The label says 17 grams of sugar.",
    "Is milk and apple juice okay for afternoon snack?",
    "Can the 4 year olds have chocolate milk at lunch?",
    "Do I need a whole grain today? Breakfast was white toast and lunch is rice."
  ];

  function proofCard(p) {
    var v = VERDICT[p.verdict] || VERDICT.UNVERIFIED;
    var bad = p.verdict === "INVALID" || p.verdict === "IMPOSSIBLE";
    var open = p.verdict === "SATISFIABLE" || p.verdict === "AMBIGUOUS";
    var head = window.h("div", { class: "proof-head" }, [
      window.levelBadge(v[0], v[1]),
      window.h("span", { class: "small muted" }, [
        "Check " + p.attempt + " of 3", window.infoBtn("attempt", "the three checks")]),
      window.h("span", { class: "when", text: window.fmtTime(p.at) + (p.latency_ms ? " · " + (p.latency_ms / 1000).toFixed(1) + " s" : "") })
    ]);
    var card = window.h("div", { class: "proof" }, [
      head,
      window.h("p", { class: "proof-q", text: "She asked: " + p.question }),
      window.h("p", { class: "proof-a" + (bad ? " struck" : ""), text: "Draft: " + p.answer })
    ]);
    if (p.rules && p.rules.length) {
      card.appendChild(window.h("blockquote", { class: "rule " + (bad ? "breaks" : "holds") }, [
        window.h("strong", { text: bad ? "The rule it breaks" : "The rule it rests on" }),
        window.h("span", { text: p.rules[0] })
      ]));
    }
    if (bad && p.stakes) {
      // The number a provider repeats: what following this answer would have cost this month,
      // from the same claim engine and rates that compute the month's claim.
      var s = p.stakes;
      card.appendChild(window.h("p", { class: "stakes" }, [
        window.h("span", { class: "money lost", text: "$" + s.month.toFixed(2) }),
        window.h("span", { class: "small muted", text: " not paid this month, had she followed it: one "
          + s.meal + " a day for " + s.children + " children over " + s.serving_days
          + " serving days at the " + s.tier.replace("_", " ") + " rate of $" + s.rate.toFixed(2) + "." }),
        window.infoBtn("lost_amount", "the lost amount")
      ]));
    }
    if (open && p.missing_facts && p.missing_facts.length) {
      card.appendChild(window.h("blockquote", { class: "rule missing" }, [
        window.h("strong", { text: "What would settle it" }),
        window.h("span", { text: p.missing_facts.slice(0, 2).join("; ") })
      ]));
    }
    if (p.verdict === "UNVERIFIED") {
      card.appendChild(window.h("blockquote", { class: "rule" }, [
        window.h("strong", { text: "Why it could not be checked" }),
        window.h("span", { text: (p.untranslated && p.untranslated.length)
          ? "The logic has no rule about: " + p.untranslated.slice(0, 2).join("; ")
          : "Nothing in the answer maps onto the meal pattern rules." })
      ]));
    }
    if (p.premises && p.premises.length) {
      // The solver's own reading of her facts, variable names and all. Shown as evidence, labelled
      // so a provider knows it is the logic's bookkeeping and not something she has to understand.
      card.appendChild(window.h("p", { class: "small muted", style: "margin:var(--s3) 0 0",
        text: "What the logic read from her facts:" }));
      card.appendChild(window.h("div", { class: "facts", style: "margin-top:var(--s1)" },
        p.premises.slice(0, 5).map(function (f) {
          return window.h("span", { class: "chip", text: f.replace(/([a-z])([A-Z])/g, "$1 $2")
            .replace(/([a-z])(\d)/g, "$1 $2").replace(/(\d)([a-z])/gi, "$1 $2").toLowerCase()
            .replace(/[a-z ]+type_/g, "").replace(/_/g, " ") });
        })));
    }
    var policy = (p.policy_version || "").split("/").pop();
    var filed = p.ledger && p.ledger.filed
      ? "Filed in S3, locked until " + p.ledger.locked_until + ". "
      : (p.ledger && p.ledger.reason ? "Not filed: " + p.ledger.reason + ". " : "");
    card.appendChild(window.h("p", { class: "stamp" }, [
      (p.verdict === "SKIPPED" ? "Proving was off. " : "Automated Reasoning policy " + (policy || "unversioned")
        + ", guardrail version " + (p.guardrail_version || "?") + ". " + filed),
      window.infoBtn(p.ledger && p.ledger.filed ? "proof_ledger" : "proof_receipt", "the proof receipt")
    ]));
    return card;
  }

  function renderAsk() {
    var ex = document.getElementById("ask-examples");
    if (ex && !ex.children.length) {
      EXAMPLES.forEach(function (q, i) {
        ex.appendChild(window.h("button", { class: "btn small", type: "button",
          title: q, onclick: function () {
            document.getElementById("ask-text").value = q;
            document.getElementById("ask-text").focus();
          } }, [["The yogurt question", "Milk and juice", "Chocolate milk", "Whole grains"][i]]));
      });
    }
    var box = document.getElementById("ask-answer");
    if (lastAsk) {
      var tone = { VALID: "ok", INVALID: "alert", IMPOSSIBLE: "alert", SATISFIABLE: "ask", AMBIGUOUS: "ask" }[lastAsk.verdict] || "";
      box.hidden = false;
      box.className = "ask-answer " + tone;
      box.innerHTML = "";
      box.appendChild(window.h("span", { class: "who",
        text: lastAsk.prove ? "Tally, after proving" : "Tally, without the tool" }));
      box.appendChild(window.h("span", { text: lastAsk.answer }));
    }
    var host = document.getElementById("proofs");
    host.innerHTML = "";
    var proofs = (state.proofs || []).slice().reverse();
    if (!proofs.length) {
      host.appendChild(window.h("p", { class: "muted small", style: "margin:0",
        text: "No answers checked yet. Ask something above, or press an example." }));
      return;
    }
    host.appendChild(window.h("h3", { style: "font-size:1rem;margin:0" },
      [proofs.length + (proofs.length === 1 ? " check today" : " checks today")]));
    proofs.forEach(function (p) { host.appendChild(proofCard(p)); });
    window.MountInfo();
  }

  function renderTrace() {
    var host = document.getElementById("trace");
    host.innerHTML = "";
    if (!traceEvents.length) {
      host.appendChild(window.h("p", { class: "muted small", text: "No events yet. Play a step." }));
      return;
    }
    traceEvents.forEach(function (e) {
      var rest = {};
      Object.keys(e).forEach(function (k) { if (k !== "kind" && k !== "at") rest[k] = e[k]; });
      host.appendChild(window.h("div", { class: "trace-row" }, [
        window.h("span", { class: "t", text: window.fmtTime(e.at) }),
        window.h("span", { class: "k", text: WORDS[e.kind] || e.kind }),
        window.h("span", { class: "d", text: JSON.stringify(rest) })
      ]));
    });
  }

  function renderAll() {
    renderStatus();
    renderSteps();
    renderMeals();
    renderSaid();
    renderAsk();
    var active = document.querySelector('[role="tab"][aria-selected="true"]').id;
    if (active === "tab-children") renderChildren();
    if (active === "tab-evening") renderEvening();
    if (active === "tab-month") renderMonth();
    if (active === "tab-trace") renderTrace();
  }


  /* Connection state -----------------------------------------------------
     Three things a person needs when something breaks: what happened, what the system did about
     it, and the one action available. */
  var connEl = null;
  function connection(message, kind, actionLabel, action) {
    if (connEl) { connEl.remove(); connEl = null; }
    if (!message) return;
    // The region goes into the document empty and is filled on the next frame. A live region
    // that is already populated when it is inserted is not reliably announced by NVDA, JAWS or
    // VoiceOver: they watch for a change inside a region they are already tracking. Building it
    // fully and then appending meant the offline banner, which is the moment announcement matters
    // most, was usually silent.
    connEl = window.h("div", { class: "conn" + (kind === "gone" ? " gone" : ""),
      role: "status", "aria-live": "polite" }, []);
    document.body.appendChild(connEl);
    var el = connEl;
    requestAnimationFrame(function () {
      if (el !== connEl) return;
      el.appendChild(window.h("span", { text: message }));
      if (actionLabel) {
        el.appendChild(window.h("button", { class: "btn small", type: "button",
          onclick: function () { connection(null); action(); } }, [actionLabel]));
      }
    });
  }
  window.addEventListener("offline", function () {
    connection("You are offline. Nothing is lost; the demo picks up where it left off.", "gone");
  });
  window.addEventListener("online", function () {
    connection("Back online.", "");
    setTimeout(function () { connection(null); }, 2500);
  });

  /* Actions --------------------------------------------------------------- */

  function pullTrace() {
    return api("/api/trace?since=" + traceCursor).then(function (t) {
      traceEvents = traceEvents.concat(t.events);
      traceCursor = t.next;
    });
  }

  function after(s) {
    state = s;
    return pullTrace().then(function () { setBusy(false); renderAll(); });
  }

  function fail(e) {
    setBusy(false);
    // setBusy(false) enables every step button, which is right during a normal run and wrong
    // here: the ordering rules in renderSteps are what stop a day being played out of sequence,
    // and a failure must not be the way around them. Re-render so a failed step leaves the board
    // exactly as locked as it was before. Guarded because this same handler catches the very
    // first /api/state call, when there is no state to render yet.
    if (state) renderAll();
    var offline = !navigator.onLine;
    var loading = !state;
    var el = document.getElementById("status");
    el.className = "status-line alert";
    if (offline) {
      el.textContent = loading
        ? "You are offline, so the day could not be loaded. Nothing was lost."
        : "You are offline, so that step did not run. Nothing was lost.";
    } else {
      el.textContent = loading
        ? "The day could not be loaded: " + e.message + "."
        : "That step did not finish: " + e.message + ". Nothing was saved.";
    }
    connection(offline ? "You are offline." : "The service did not answer.",
      "gone", "Try again", function () { location.reload(); });
  }

  /* Playing it through -----------------------------------------------------
     Each step is a real agent run, so there is a pause between them. Someone watching, or
     recording, should not have to sit with a finger over the button for that pause. */
  var playing = false;

  function playThrough() {
    if (busy || playing) return;
    playing = true;
    (function nextOne() {
      var left = state.steps.filter(function (s) { return !s.done; });
      if (!left.length) { playing = false; renderAll(); return; }
      var s = left[0];
      setBusy(true, "Running: " + s.detail);
      api("/api/step", { method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ step: s.id }) })
        .then(after)
        .then(function () { setTimeout(nextOne, 900); })
        .catch(function (e) { playing = false; fail(e); });
    })();
  }

  function runStep(id, detail) {
    if (busy) return;
    setBusy(true, "Running: " + detail);
    api("/api/step", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ step: id }) }).then(after).catch(fail);
  }

  function answer(qid, text) {
    if (busy) return;
    setBusy(true, "Recording your answer");
    api("/api/answer", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ question_id: qid, answer: text }) }).then(after).catch(fail);
  }

  function askTally(text, prove) {
    if (busy || !text.trim()) return;
    // Honest about time: a proof is a few seconds on top of the model call.
    setBusy(true, prove ? "Asking Tally. Proving the answer takes about ten seconds."
                        : "Asking Tally without the tool, as it was before.");
    api("/api/ask", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ text: text, prove: prove }) })
      .then(function (s) { lastAsk = s.ask; return after(s); }).catch(fail);
  }

  function reset() {
    lastAsk = null;
    setBusy(true, "Resetting to Tuesday 07:38");
    api("/api/reset", { method: "POST" }).then(function (s) {
      traceEvents = []; traceCursor = 0;
      return after(s);
    }).catch(fail);
  }

  function selectTab(id) {
    document.querySelectorAll('[role="tab"]').forEach(function (t) {
      var on = t.id === id;
      t.setAttribute("aria-selected", String(on));
      document.getElementById(t.getAttribute("aria-controls")).hidden = !on;
    });
    if (id === "tab-children") renderChildren();
    if (id === "tab-evening") renderEvening();
    if (id === "tab-month") renderMonth();
    if (id === "tab-trace") renderTrace();
    if (history.replaceState) history.replaceState(null, "", "#" + id.replace("tab-", ""));
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll('[role="tab"]').forEach(function (t) {
      t.addEventListener("click", function () { selectTab(t.id); });
    });
    document.getElementById("reset").addEventListener("click", reset);
    var form = document.getElementById("ask-form");
    if (form) {
      form.addEventListener("submit", function (ev) {
        ev.preventDefault();
        askTally(document.getElementById("ask-text").value, document.getElementById("ask-prove").checked);
      });
      document.getElementById("ask-prove").addEventListener("change", function (ev) {
        document.getElementById("ask-mode").textContent = ev.target.checked
          ? "On: the agent has the prove_answer tool."
          : "Off: the agent exactly as it shipped in September, with no way to check.";
      });
    }
    api("/api/state").then(function (s) { state = s; return pullTrace(); }).then(function () {
      renderAll();
      var hash = (location.hash || "").replace("#", "");
      if (hash && document.getElementById("tab-" + hash)) selectTab("tab-" + hash);
    }).catch(fail);
  });
})();
