# Final Presentation Deck (8-min slot, engineered against the rubric)

This deck is designed to maximize the score on
`course_files_export_text/Final Presentation-rubric-2.txt` within the
**8-minute slides+demo + 2-minute Q&A** time budget.

The rubric has **30 total points** split into:

- **A. Project Quality (21 pts)**
  - Technical Soundness & Model Use (8)
  - Problem Fit & Impact (4)
  - Execution & Project Completeness (7)
  - Design & UX (2)
- **B. Presentation Quality (9 pts)**
  - Slide Clarity & Organization (4)
  - Demo Quality (3)
  - Q&A Performance (2)

Every slide below is annotated with the rubric categories it targets and how
much time to spend on it. **Total run time: 8:00 presentation + 2:00 Q&A.**

---

## Time budget at a glance (8 minutes flat)

| # | Slide | Time | Cumulative | Presenter |
|---|---|---:|---:|---|
| 1 | Title | 0:10 | 0:10 | A |
| 2 | Problem | 0:30 | 0:40 | A |
| 3 | Solution snapshot | 0:30 | 1:10 | A |
| 4 | System architecture | 0:40 | 1:50 | B |
| 5 | **AI use #1: Input understanding** (Llama 3.2 3B + regex fast path) | 0:50 | 2:40 | B |
| 6 | **AI use #2: Output explanation** (Llama 3.2 3B per-course rationales) | 0:40 | 3:20 | B |
| 7 | **AI use #3: Review summarization** (Llama 3.1 8B sentiment AI) | 0:40 | 4:00 | B |
| 8 | Ranking pipeline integration (where AI inputs land) | 0:40 | 4:40 | B |
| 9 | **LIVE DEMO (2 scenarios)** | 2:15 | 6:55 | C |
| 10 | Limitations + future work + close | 0:40 | 7:35 | C |
| – | Buffer (transitions, laptop quirks) | 0:25 | 8:00 | All |
| – | Q&A | 2:00 | 10:00 | All |

The deck is structured around **three GenAI deep-dives** (Slides 5–7),
one per LLM use case, followed by a single integration slide (Slide 8)
that shows where each AI-derived input lands in the ranker. This puts
AI explicitly at the center of the technical narrative — directly
serving the rubric's *"clear explanation of models/APIs used; demo
shows meaningful GenAI functionality"* criterion.

The 25s buffer is tighter than before but still absorbs typical
CPU-laptop hiccups (FastAPI cold-start, scroll fumbles). Don't fill
it; treat it as flex.

Suggested presenter split for 3 people: **A = problem framing, B = technical
backbone, C = demo + close.** Adjust to your team's strengths.

---

## Rubric → Slide map (cheat sheet)

| Rubric category | Pts | Slides that earn it |
|---|---|---|
| Technical Soundness & Model Use | 8 | 4, **5–7 (the three GenAI deep-dives)**, 8 |
| Problem Fit & Impact | 4 | 2, 3, 10 |
| Execution & Completeness | 7 | 5, 8 (0.0000 violation rate), 9 (live demo) |
| Design & UX | 2 | 3, 9 |
| Slide Clarity & Organization | 4 | All — apply visual discipline |
| Demo Quality | 3 | 5–7 (LLM use cases pre-explained) + 9 (live demo) + backup video |
| Q&A Performance | 2 | Q&A block + backup slides 11–13 |

---

## Slide 1 — Title (0:10)

**Targets:** Slide Clarity (sets tone).

**Content:**

- Title: **GenAI-Powered Curriculum Advisor**
- Subtitle: **Integrating Professor Sentiment Signals into Intelligent Course Planning**
- Names: Leigh Apotheker · Nabeel Rana · Cami Surucu
- CSC 603/803 Capstone — Spring 2026

**What to say (1 sentence):** *"We built a conversational curriculum advisor
that combines deterministic prerequisite reasoning with professor-sentiment
signals — running entirely on this laptop's CPU."*

---

## Slide 2 — The problem (0:30)

**Targets:** Problem Fit & Impact (4 pts).

**Content (one image + three short bullets):**

- Students juggle **structured constraints** (prereqs, degree progress) **and**
  **unstructured signals** (professor reputation, perceived difficulty).
- Today these are evaluated on **separate platforms** — degree planner +
  RateMyProfessor + spreadsheet.
- Result: **fragmented, slow, error-prone** course selection every semester.

**What to say:** *"Official planners only check that you're allowed to take a
course. They don't tell you whether the section that's actually offered will
be a good experience. Students fix that themselves with browser tabs and
group chats. We unified those two halves."*

---

## Slide 3 — Our solution at a glance (0:30)

**Targets:** Problem Fit (4) + Design & UX (2).

**Content:** A single annotated screenshot of the chat panel + recommendation
panel. Three callouts pointing to:

1. **Conversational input** ("I'm a BSCS senior, prefer high-rated profs")
2. **Sentiment-scored course cards** — sentiment score computed from
   RMP's structured fields; green/red review-summary tags written
   offline by Llama 3.1 8B from review texts
3. **Per-course rationale** (template by default, LLM-generated optional
   via env var)

**What to say:** *"You talk to it like a friend. Behind the scenes
GenAI does meaningful work in three places — turning your free-form
prompt into structured intent, writing the rationale on every card,
and summarizing each professor's reviews into the green tags you read.
A deterministic engine filters out anything you can't take and a
multi-objective ranker picks the plan, so the system stays
reproducible. The next three slides go deep on each LLM use case, and
the slide after shows where each one lands in the ranker."*

---

## Slide 4 — System architecture (0:40)

**Targets:** Technical Soundness & Model Use (8 pts) — biggest payoff slide.

**Content:** A clean left-to-right diagram with four columns. Each box
labeled with the slide that deep-dives it.

1. **Frontend (browser)** — HTML / CSS / vanilla JS chat UI; `fetch`
   to backend.
2. **Backend (FastAPI, all local) — two service layers:**
   - **Chat service layer** *(Slide 5)*: Llama 3.2 3B intent extractor
     with regex fast path for clean prompts. Owns conversation state
     across turns.
   - **Advisor service layer** *(Slide 8)*: deterministic 7-stage
     pipeline. Calls `PrerequisiteService` + `rmp_service`, reads
     `professor_sentiment_features` (sentiment score: structured-field
     math; LLM-generated review summaries — *Slide 7*).
3. **Data layer (SQLite)** — `course_prerequisites`, `degree_programs`,
   `class_schedules`, `professor_sentiment_features`.
4. **LLMs (Ollama, local, CPU)** — Llama 3.2 3B (chat intent + live
   per-card rationales, *Slides 5–6*), Llama 3.1 8B (offline
   review-text summarization for UI tags, *Slide 7*).

**Arrow semantics:**

- **Solid arrows** = deterministic data flow (frontend ↔ chat layer,
  chat → advisor, advisor → SQLite reads).
- **Dashed arrow #1** (chat layer ⇢ Llama 3.2 3B) = LLM intent
  extraction; **regex fast path** is an optimization on top.
- **Dashed arrow #2** (offline build script ⇢ Llama 3.1 8B ⇢
  `llm_sentiment_summary` columns of `professor_sentiment_features`)
  = **build-time pipeline** that fills review-summary *text* only.
  The numeric `final_sentiment_score` column in the same table is
  written by a separate calibrated formula, not by the LLM.

**Three places we deliberately deploy GenAI — each gets its own deep-dive:**

1. **Input understanding** *(Slide 5)* — Llama 3.2 3B parses free-form
   student phrasing into structured intent JSON. *Why an LLM:* regex
   handles common phrasings, but the long tail (*"I'm thinking about
   wrapping up next semester with something AI-flavored"*) needs
   meaning, not pattern matching.
2. **Output explanation** *(Slide 6)* — Llama 3.2 3B writes 1–2 sentence
   "why this course" rationales for every recommendation **live, per
   chat turn**, with a deterministic template fallback if Ollama is
   unavailable. *Why an LLM:* static templates feel canned; the model
   adapts each rationale to the specific student's major, completed
   courses, and the course's sentiment score so each card reads
   naturally and reflects the *individual* student's context.
3. **Review summarization** *(Slide 7)* — Llama 3.1 8B turns each
   professor's raw RMP review prose into a 1–2 sentence summary plus
   pros/cons that power the green/red tags students see on every card.
   *Why an LLM:* 1–5 star ratings compress the nuance students care
   about (*"tough but fair"* vs *"easy A"*) into a single number; only
   reading the prose surfaces the texture.

**Slide 8 then shows where each AI-derived input lands in the
ranker** — intent JSON at the top, rationales and review tags
attached to each card at the bottom, and reproducible ranking math
(prereq DAG, scoring formula, time-conflicts, unit cap) in between.

**What to say:** *"GenAI shows up in three deliberate places — each
chosen because rule-based alternatives would have been worse. Llama
3.2 3B parses free-form prompts into structured intent when regex
can't generalize, and writes per-course rationales so each card has
prose explaining why it appeared. Llama 3.1 8B turns RMP review prose
into the green/red summary tags students see — capturing nuance that
1–5 stars can't. **Every word of language students see came from an
LLM.** The ranker math itself is deterministic so the system stays
reproducible, but the GenAI work is what makes it useful. The next
three slides go deep on each LLM use case, and Slide 8 shows where
they all land in the ranker."*

---

## Slide 5 — AI use #1: Input understanding (Llama 3.2 3B + regex fast path) (0:50)

**Targets:** Technical Soundness (8) + Demo Quality (3) — first of three GenAI deep-dives.

**Frame:** Before any ranking can happen we need a *structured*
request — major, term, completed courses, preferences, blocked
times — extracted from a free-form student prompt. **This is where
the LLM lets the chat understand arbitrary phrasing.**

**Two-tier intent extractor** (`backend/app/services/chat_service.py`):

- **LLM tier — Llama 3.2 3B via local Ollama, T = 0, capped at 384
  output tokens, ~5–10 s on CPU.** Reads any reasonable English
  sentence and returns strict JSON intent. *"Hey, I'm thinking about
  wrapping up next semester with something AI-flavored"* →
  `{ major: "BSCS", term: "Spring 2027", preferences_text: "AI elective", … }`.
  **This is what gives the chat conversational generality.**
- **Regex fast path — deterministic, ~50 ms.** When a prompt is
  unambiguous (major, term, course codes literally present), we
  extract the same fields in milliseconds and skip the LLM. Same JSON
  shape, same downstream pipeline. Fallback is automatic and
  bidirectional: any required field missing or ambiguous → LLM picks
  it up. Toggle `CURRICULUM_ADVISOR_FAST_INTENT=0` forces LLM every
  turn.

**Why an LLM here:** regex matches *patterns*. Only an LLM
generalizes over phrasings the user hasn't been trained to produce.

**Where the extracted intent goes — preferences become scoring weights:**

| User phrasing | Extractor flag | Effect on the ranker |
|---|---|---|
| *"I want an AI elective"* | `must_include_topics = ["ai"]` | Keyword match against course titles + descriptions → CSC 665 surfaces |
| *"I prefer professors with great reviews"* | `prefer_high_rated_professors = true` | `w_sentiment` flips 0 → 0.35 |
| *"Keep it under 9 units"* | `max_units_per_semester = 9` | Hard cap on the unit-DP stage |
| *"I can't do evening classes"* | `blocked_time_windows = [{17:00–22:00, weekdays}]` | Time-conflict layer drops or swaps offending sections |

**Per-turn state management:** all extracted fields **merge** across
turns, never overwrite. Scenario B's *"Actually, I can't do evening
classes"* works because Scenario A's major + term are still in scope.

**What to say:** *"First place GenAI does meaningful work: turning
natural language into a structured request. Llama 3.2 3B handles
arbitrary student phrasing — any reasonable English sentence — and
returns strict JSON intent. We layered a regex fast path on top that
catches clean prompts in milliseconds, so the demo runs at CPU speed
without sacrificing the LLM's coverage; the fallback is automatic.
Once intent is extracted, preferences become scoring weights — 'great
reviews' flips `w_sentiment` to 0.35, 'AI elective' surfaces CSC 665
by keyword-matching course titles. State merges across turns, which
is how Scenario B's evening-class constraint piggybacks on Scenario
A's major and term."*

> **Demo note:** if anyone in Q&A asks to *see* the LLM intent path
> live, type a vague prompt — the regex fails, Llama 3.2 3B engages,
> and the audience sees real-time GenAI in ~5–10 s.

---

## Slide 6 — AI use #2: Output explanation (Llama 3.2 3B per-course rationales) (0:40)

**Targets:** Technical Soundness (8) — second of three GenAI deep-dives.

**Frame:** Every course card carries a 1–2 sentence rationale
explaining *"why this course?"*. **In the demo configuration,
Llama 3.2 3B writes that prose live — one batched LLM call per chat
turn, contextual to the specific student.**

**The runtime LLM call** (`generate_course_rationales` in
`backend/app/services/llama_sentiment_service.py`):

- **Model:** Llama 3.2 3B via local Ollama, `T = 0`,
  `max_tokens = 512`, ~5–10 s on CPU.
- **Input:** for each recommended course, a structured block —
  `code`, `title`, `group`, `units`, `prereq`, `professor`,
  `sentiment` (the numeric score from Slide 7), `rmp_rating`,
  `rmp_difficulty` — plus the student's `major`, `term`,
  `completed_courses`, and free-form preferences.
- **Output (strict JSON):** `{"rationales": {"CSC 510": "Builds on
  your CSC 415 background — …", …}}`
- **Batched:** all 5–9 cards covered in one LLM call, not one per
  card.

**Why an LLM here:** static templates feel canned. *"This course
satisfies a major requirement"* reads identically on every card —
students learn to ignore it. The LLM adapts each rationale to *which*
requirement, *which* major, and *which* prior courses. *"Builds on
the OS foundations from CSC 415"* vs *"Required upper-division
elective for the AI track"* land very differently — even though both
might describe the same recommendation for two different students.

**Graceful degradation** (`scripts/prebuild_demo_rationales.py`):
when Ollama is unreachable or the LLM call times out (20 s), every
unfilled card falls back to a deterministic template — catalog title
+ requirement group + first sentence of the course description,
stitched by Python string formatting and pre-built once at deploy
time. The chat status line shows `rationales: llm`, `template`, or
`llm+template` so you always know which path served each card.

**What to say:** *"Second place GenAI shows up: every course card
carries a 1–2 sentence rationale. In the live demo, Llama 3.2 3B
writes those rationales fresh — one batched LLM call per chat turn
that reads each course's metadata, the sentiment score from Slide 7,
and the student's context. So a senior who's already taken CSC 415
sees a different rationale on CSC 510 than a junior who hasn't.
That's about a 5–10 second wait on a CPU laptop, which is exactly
what you'll see in the live demo when the cards take a moment to
appear. We have a deterministic template path that takes over if
Ollama is unreachable so the system never breaks — but during the
demo every word of the rationale text comes from a model."*

---

## Slide 7 — AI use #3: Review summarization (Llama 3.1 8B sentiment AI) (0:40)

**Targets:** Technical Soundness (8) — third of three GenAI deep-dives.

**Frame:** Every course card carries a green/red review-summary tag —
*"Amazing lectures, fair grading"* / *"Tough grader, slow feedback."*
**Those tags are Llama 3.1 8B reading actual RateMyProfessor
reviews — the AI work students consume every time they see a
recommendation.**

**The summarization pipeline** (`scripts/build_professor_sentiment_features.py`):

- **Input:** up to 8 of the professor's most recent RMP review texts
  (each capped at 500 chars).
- **Model:** Llama 3.1 8B via local Ollama, **T = 0**.
- **Prompt:** *"What do the reviews generally say about this
  professor? Write 1–2 complete sentences. Focus on teaching quality,
  clarity, engagement, organization, accessibility, and grading
  practices."*
- **Output (strict JSON):**
  - `summary` — 1–2 sentence prose → green/red tag on every card
  - `pros[]`, `cons[]` — strengths/weaknesses (UI + Q&A backup)

**Why an LLM and not just RMP's stars:** structured 1–5 ratings can't
distinguish *"tough but fair, learned a lot"* from *"easy A, didn't
learn much"* — both can be 4.5 stars. **Only reading the prose
surfaces the distinction students care about.**

**Why 8B over 3B:** review summarization needs nuance the smaller 3B
model couldn't reliably capture at temperature = 0.

**Why offline / build-time:** the 4.7 GB model would otherwise block
the demo on a CPU laptop. Building once at deploy means the demo gets
LLM-authored UX with **zero inference cost at runtime**.

**The numeric `sentiment` value the ranker reads** is a *separate*
parallel artifact — a calibrated formula over RMP's structured fields
(`rating`, `would_take_again_pct`, `level_of_difficulty`) with
Bayesian shrinkage `n / (n + 10)`. Slide 8 shows where it integrates
with the scoring math.

**What to say:** *"Third place GenAI shows up: every green/red review
tag students see on every card is Llama 3.1 8B's summary of that
professor's actual RMP reviews. Up to 8 review texts go in; a 1–2
sentence prose summary plus pros and cons come out at build time. We
use the 8B model because review summarization needs nuance the 3B
couldn't catch at temperature zero, and we build offline because a
4.7-gigabyte model would block the demo on a CPU laptop. The numeric
sentiment score the ranker reads is a separate calibrated formula
over RMP's structured stats — that's the integration story on the
next slide."*

---

## Slide 8 — Ranking pipeline integration (where AI inputs land) (0:40)

**Targets:** Technical Soundness (8) + Execution & Completeness (7) — the integration + reliability slide.

**Frame:** The three LLM use cases on Slides 5–7 produce **AI-derived
inputs**. This slide shows where those inputs land in the
deterministic ranker — and what makes the system reliable.

**The pipeline** (one linear flow inside `AdvisorService.recommend`):

```
                Llama 3.2 3B  intent JSON   (Slide 5)
                              │
                              ▼
1. Load catalog + sections + sentiment + RMP   (SQL)
2. Prereq DAG validation                       (DNF graph traversal)
       → drops un-takeable courses
       → 0.0000 violation rate across packaged eval scenarios
3. Preference parsing                          (regex + keyword match)
4. Multi-objective scoring                     (closed-form formula)
       score = (w_progress·progress + w_workload·lightness
              + w_sentiment·sentiment + w_difficulty·easiness) / Σw
       · sentiment value = calibrated RMP-structured-fields formula (Slide 7)
5. Group selection                             (DP over unit budget)
6. Time-conflict layer + section-swap          (interval arithmetic)
       → tries alternate sections before dropping (Scenario B)
7. Semester unit cap
                              │
                              ▼
       Llama 3.2 3B rationales (Slide 6)
       Llama 3.1 8B review tags (Slide 7)
                              │ attach to each surviving recommendation
                              ▼
                          Final cards
```

**Where AI flows in vs. out vs. through:**

- **In:** Llama 3.2 3B intent JSON enters at the top → drives the
  whole request shape.
- **Out:** Llama 3.2 3B rationales + Llama 3.1 8B review tags attach
  to each card *after* ranking → make the recommendation legible.
- **Through:** the ranking math itself is reproducible — same intent
  + same data = same plan, every time.

**Reliability properties (Q&A defenses):**

- **0.0000 prereq violation rate** measured by
  `scripts/evaluate_sentiment_impact.py` across packaged scenarios.
  Proposal Objective 2 — *measurably* satisfied.
- **Reproducibility.** Every ranking stage is deterministic; the LLM
  contributions are text the user reads, never numbers the ranker
  uses.
- **Graceful degradation.** Ollama crash → regex fast path still
  extracts intent on clean prompts; templated rationales attach;
  system keeps producing plans.

**What to say:** *"This is where it all comes together. Llama 3.2 3B
intent flows into the top of the pipeline. Llama 3.2 3B rationales
and Llama 3.1 8B review tags attach to each card at the bottom. In
between, seven deterministic stages — including the prereq DAG with a
**measured zero-violation rate**, the multi-objective scoring formula
on screen, and the time-conflict handling that powers Scenario B's
silent section-swap. The ranking math is reproducible so the same
inputs produce the same plan every time, and the LLM contributions
are language the user reads, never numbers the ranker uses. That
split is the design point."*

---

## Slide 9 — LIVE DEMO (2:15)

**Targets:** Demo Quality (3) + Execution (7) + Design & UX (2).

> **Latency note:** the backend (`scripts/run_backend.sh`) defaults
> the demo to **live LLM rationales** — Llama 3.2 3B writes each
> card's rationale prose freshly per chat turn (~5–10 s on CPU,
> batched across all cards). Regex intent fast-path keeps the front
> half of the request (~50 ms) so total response time is ~5–10 s.
> If you ever need the lightning-fast non-LLM mode, set
> `CURRICULUM_ADVISOR_RUNTIME_RATIONALES=0` to fall back to
> deterministic templates. See `docs/demo-script.md`.

**Two scenarios from `docs/demo-script.md`. The chat in Scenario B
continues from Scenario A — do not click "New chat" between them.**

### Scenario A — Senior-year sentiment-aware planning (~75s)

Type:

```text
I'm a BSCS senior, planning Fall 2026. I've completed CSC 210, CSC 220,
CSC 230, CSC 256, CSC 340, CSC 415, MATH 226, MATH 227, MATH 245, PHYS 220.
I want an AI elective and I prefer professors with great reviews.
```

Point out (lead with GenAI-authored content, then context):
- **The 5–10 second wait after pressing Enter is itself part of the
  demo:** *"Llama 3.2 3B is writing fresh rationale prose for every
  card in real time, on this CPU laptop, no cloud calls. That's the
  live GenAI you're watching."* (Don't apologize for the latency —
  frame it as the local-LLM proof point.)
- **Course cards — every card carries LLM-authored language:**
  - The **green/red review tag** (e.g. *"Amazing lectures, fair
    grading"*) is Llama 3.1 8B's offline summary of that professor's
    RateMyProfessor reviews. *"Every word of that tag came from a
    model reading the actual review prose at build time."*
  - The **per-course rationale** ("why this course") is Llama 3.2 3B
    prose, **just written live in that 5–10 second wait.** *"It
    reads each course's metadata, the sentiment score, and your
    completed-courses list — so a senior who's taken CSC 415 sees a
    different rationale on CSC 510 than a junior would."*
- **Conversation state (debug panel):** chat extracted major, term,
  and completed courses from free-form English. *"Either Llama 3.2 3B
  on an ambiguous prompt, or the regex fast path on a clean one —
  same intent JSON either way. This prompt was clean enough that the
  regex path caught it; status line below shows which one fired."*
- **Status line** `intent: regex (fast path) · rationales: llm` —
  *"Regex on the input side, live Llama 3.2 3B on the output side.
  If Ollama crashes mid-demo the status line flips to `template` and
  every card still gets a rationale from the deterministic fallback —
  graceful degradation by design."*
- **The reply line** *"Skipped N courses with unmet prereqs
  (deterministic check)"* — half-beat callout for Objective 2 (the
  prereq DAG) before moving on.

### Scenario B — Constraint changes the schedule (~60s)

> **Continue the same chat from Scenario A** — do NOT click "New chat".
> This prompt has no major or term in it; it relies on the conversation
> state Scenario A established.

Type into the same chat:

```text
Actually, I can't do evening classes.
```

Point out:
- **Another 5–10 second wait** — Llama 3.2 3B is rewriting rationales
  for the new card set (e.g. CSC 317's swapped section gets a fresh
  rationale that mentions the new instructor). *"Same live GenAI as
  Scenario A — the rationales adapt every time the plan changes."*
- The schedule grid's evening rows empty out (5 PM onwards for every
  weekday is now blocked).
- CSC 317 stays in the plan but **its section silently swaps** from
  `TuTh 5:00 PM (Nina Mir)` to `MoWe 11:00 AM (Andrew Scott)`. The
  advisor walks every offered section of each recommended course and
  picks one that satisfies the new blocked window *and* doesn't overlap
  any other selected class — instead of dropping the course and
  shrinking the unit count.
- Total units stay at 9 — the user's requested load is preserved
  through a constraint change. CSC 665 (AI elective) and CSC 510 keep
  their original sections.
- Open the **Conversation state (debug)** panel: major, term, completed
  courses, and the AI-elective preference from Scenario A are all still
  in state. Only `blocked_time_windows` was added by this turn — that's
  multi-turn state persistence working.

> **Backup video required.** Pre-record both scenarios the night before,
> queued in a video player on a second monitor. If the laptop
> misbehaves, switch and keep talking.

---

## Slide 10 — Limitations + future work + close (0:40)

**Targets:** Problem Fit (4) + sets up Q&A.

**One-sentence summary:**

> A unified, sentiment-aware curriculum advisor that respects
> prerequisites deterministically and runs entirely on a CPU laptop.

**Current limitations (be honest — it earns trust):**

- **Single sentiment source.** RMP self-selects toward students with
  strong opinions. Confidence-shrinkage protects thin-data professors
  from being unfairly penalized, but the underlying selection bias
  remains.
- **One-term planning horizon.** The ranker optimizes a single
  semester at a time. Course rotations across semesters (e.g.
  upper-division electives offered only in spring) aren't modeled.
- **English-only.** Both the regex extractor and the Llama 3.2 3B
  fallback assume English input.
- **Catalog-specific.** The prereq DAG and degree requirements are
  imported from SF State CSC. Porting to another department or
  university is a manual catalog-import step today.

**Future work:**

- **Multi-semester planning** with course-rotation awareness — turn
  the single-semester ranker into a 2–4 semester planner that respects
  which courses are typically offered when.
- **Calibrated sentiment uncertainty** — Bayesian credible intervals
  over `sentiment_score`, surfaced in the UI as a confidence band
  instead of a single point value.
- **Pluggable degree imports** — generalize the catalog parser so a
  CSV or web scrape of any university's catalog can produce a working
  advisor without code changes.
- **Multiple sentiment sources** — augment RMP with internal course
  evaluations or anonymized student surveys to reduce single-source
  bias.

**What to say:** *"Four honest limitations and four future-work
directions on screen. The biggest quality win is reducing single-source
sentiment bias by adding internal course evaluations. The biggest
scope expansion is multi-semester planning, which the prereq DAG
already supports. Pluggable catalogs would let other departments
reuse the engine without code changes. English-only remains a known
gap pending broader multilingual model support. Thank you — happy to
take questions."*

---

## Backup slides (held in reserve for Q&A)

### Slide 11 — Anticipated Q&A reference

Prepared answers for likely classmate questions:

**Q: "What stops the LLM from hallucinating a course code?"**
A: The LLM only emits intent fields. Course identity is resolved against the
SQLite catalog, and `PrerequisiteService` re-validates every candidate
before ranking.

**Q: "Why a small 3B model? Why not GPT-4?"**
A: Three reasons — (1) the demo machine is CPU-only, (2) zero cloud
dependency for student data privacy, (3) the LLM only does structured
extraction, which a 3B model handles reliably at temperature 0.

**Q: "Where is your DAG actually stored?"**
A: SQLite tables `course_prerequisites` and `course_prerequisite_notes`.
`PrerequisiteService.build_prerequisite_graph()` returns the in-memory
adjacency map.

**Q: "How do you measure prerequisite violation rate?"**
A: `scripts/evaluate_sentiment_impact.py` runs the advisor on packaged
scenarios, then re-checks every recommended course against the validator
with the student's effective completed set. Across every packaged
scenario CSV the violation count is exactly zero.

**Q: "What if Ollama crashes during the demo?"**
A: Regex fallback for intent + template rationales. Validation, ranking,
and constraint handling are unaffected because none of them depend on the
LLM. We can demonstrate this on request — `pkill -f "ollama serve"` and
the next chat turn returns sub-second with the status line flipped to
`intent: regex fallback`. We chose not to show it live to keep the demo
focused on the user-facing capabilities.

**Q: "How is sentiment integrated into the ranking?"**
A: Two layers. (1) **The LLM layer:** Llama 3.1 8B reads each
professor's RMP review prose offline and generates the green/red
summary tags students see on every card — that's the AI work students
actually consume, and it's how the ranking change becomes legible to
them. (2) **The ranking layer:** `w_sentiment` is a weighted term in
the scoring formula, zero by default, activated when the user
expresses a "high-rated professors" preference. The numeric value
plugged into that term is computed from RMP's structured rating,
would-take-again, and difficulty fields with a Bayesian-shrinkage
calibration. We split the two so the AI does the language work it's
best at while the ranking signal stays reproducible across runs.

**Q: "What's novel here vs. an existing degree planner?"**
A: Two things — (1) the conversational interface that infers preferences
from free text, and (2) the integration of unstructured sentiment data
while still guaranteeing prereq correctness. Existing planners do one or
the other, not both.

**Q: "Is sentiment data biased?"**
A: Yes — RMP self-selects toward strong opinions. We confidence-shrink
scores toward the prior mean so professors with few reviews aren't
over-penalized, and we display the underlying rating count so users can
judge for themselves.

### Slide 12 — Architecture deep-dive (file paths)

For deeper Q&A on implementation:

- `backend/app/api/routes/advisor.py` (FastAPI routes)
- `backend/app/services/chat_service.py` (orchestration)
- `backend/app/services/advisor_service.py` (ranking + selection)
- `backend/app/services/prerequisite_service.py` (DAG validation)
- `backend/app/services/llama_sentiment_service.py` (all LLM calls)
- `scripts/import_course_prerequisites.py` (catalog → DAG)
- `scripts/build_professor_sentiment_features.py` (RMP → features)
- `scripts/evaluate_sentiment_impact.py` (eval harness)

### Slide 13 — Data ethics statement

For if a reviewer pushes on the RMP question:

- Reviews are publicly posted under RMP's terms; we cache only what's needed
  to compute aggregates.
- We do not display individual reviewer text in the UI.
- We summarize using a local LLM, so no third-party processor sees the data.
- Sentiment is one input to a multi-objective ranking, never the sole basis
  for any recommendation.

---

## Production checklist (the night before)

- [ ] `ollama pull llama3.2:3b` and `ollama pull llama3.1` on the demo laptop.
- [ ] `bash scripts/run_backend.sh` once — verify the warm-up log line.
- [ ] `bash scripts/run_frontend.sh` and click through Scenarios A and B
      end-to-end (without clicking "New chat" between them).
- [ ] Time the full deck end-to-end at least twice. Goal: 7:30–7:35 so
      the 25s buffer stays intact.
- [ ] Record a 2-3 min screen-capture backup of Scenarios A and B.
- [ ] Stage a side terminal with `pkill -f "ollama serve"` and
      `ollama serve &` ready to run, in case a Q&A question asks for the
      failover demo on the spot — you'll be fluent, not flustered.
- [ ] Re-run `scripts/evaluate_sentiment_impact.py` once to confirm the
      **0.0000 prereq violation rate** still holds — the headline number
      lives on Slide 8 and is the single most important Q&A defense.
- [ ] Disable system notifications and set the laptop to "Do Not Disturb."
- [ ] Plug in power. Mirror the display.
- [ ] Decide presenter order and rehearse the handoffs (3-2-1 rule:
      finish, three-second pause, hand off).

## Per-rubric tactics summary

**Technical Soundness (8 pts) — earn the 8:** keep Slide 4 visible
while explaining the architecture; spend the bulk of the deep-dive
time on Slides 5–7 (the three GenAI use cases) — *"clear explanation
of models/APIs used"* is the rubric language and these three slides
hit it directly. Mention temperature = 0, the warm-up, and *why* an
LLM is the right tool for each use case.

**Problem Fit (4 pts) — earn the 4:** open and close on the
"fragmented process today" framing. Tie it back at the end (Slide 10).

**Execution (7 pts) — earn the 7:** the live demo (Slide 9) must hit
two clean, distinct scenarios with no dead ends; Slide 8's **0.0000
violation rate** has to be voiced out loud (not just shown); the deck
must finish under 8:00.

**Design & UX (2 pts) — earn the 2:** keep the chat panel clean during
the demo. No console open, no debug panel expanded except when
narrating it.

**Slide Clarity (4 pts) — earn the 4:** at most ~25 words per slide,
one core idea per slide, consistent typography, no walls of text.

**Demo Quality (3 pts) — earn the 3:** rehearse the demo five times.
Have the backup video. The narration should lead with LLM-authored
content (green review tags, rationale prose) — every word students
read on a card came from a model, and the rubric explicitly rewards
showing meaningful GenAI functionality in the demo.

**Q&A (2 pts) — earn the 2:** rehearse Slide 11 answers (Q&A backup) out loud.
Pause half a second before answering — it reads as confidence.

## Practice timing rule

The deck targets **7:35** with a 25s buffer at the end. If your dry-run
runs **over 8:00**, cut from these in order:

1. Slide 8 — drop the ASCII pipeline diagram; describe the pipeline
   inline as "seven stages, prereq DAG to unit cap."
2. Slide 4 — drop the "Arrow semantics" callout.
3. Slide 10 — drop one of the four limitations bullets.
4. Slide 5 — drop the four-row "user phrasing → flag → effect" table;
   keep the LLM tier and regex fast-path bullets.
5. Slide 6 — drop the pre-build pipeline ASCII; describe in one
   sentence.
6. Slide 7 — drop the "Why 8B over 3B" line.
7. Slide 5 — drop the "Per-turn state management" paragraph (only
   if you're already cutting Slide 5's table — otherwise the merge
   behavior is needed for Scenario B's narration).

(Both demo scenarios are load-bearing — A establishes the system, B
proves it adapts mid-conversation. Don't cut either of them. The
three GenAI deep-dive slides are the rubric's anchor for Technical
Soundness — cut content within them, not the slides themselves.)

If your dry-run finishes **under 6:30**, you have headroom — add:

1. One extra sentence on Scenario A pointing at the per-course
   rationale text and reminding the audience it came from Llama 3.2 3B.
2. One sentence on Slide 8 about the prereq DAG's `concurrent_allowed`
   flag (it lets you take a course alongside a prereq when the catalog
   explicitly permits it).
3. Read out the `Skipped N courses with unmet prereqs` line on
   Scenario A and pause for a beat — that's a free Objective 2 callout
   backed by the **0.0000 violation rate** on Slide 8.
