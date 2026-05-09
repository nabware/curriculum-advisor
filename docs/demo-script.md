# Live Demo Script

A walk-through of every claim in the Capstone Project Proposal in roughly 5
minutes, designed for a CPU-only laptop running Ollama + FastAPI + the static
frontend on `localhost`.

## Latency profile (CPU laptop)

The chat backend has three response modes. Pick the one that matches the
moment in your demo:

| Mode | How to enable | Typical response time | When to use |
|---|---|---:|---|
| **Fast (default)** | nothing — out of the box | **~50 ms** | Most demo turns. Regex extracts intent when prompt is clear; per-course rationales come from pre-built templates. |
| **LLM intent only** | use a vague prompt that regex can't parse (e.g. *"I'm thinking about ML next semester"*) | ~5-10 s | When you want to **show** the LLM intent extractor running. Status line reads `intent: LLM`. |
| **Full GenAI (LLM intent + LLM rationales)** | start backend with `CURRICULUM_ADVISOR_RUNTIME_RATIONALES=1 bash scripts/run_backend.sh` | ~15-25 s | "Wow moment" only — explicit per-course explanations generated for *this* student. Reserve for one scenario. |

For an 8-minute demo, **start in Fast mode**. If you want to demo the LLM
rationale path, restart the backend with the env var set in advance (or
pre-record a short clip of it).

## Pre-flight checklist

Run these once before the audience arrives:

```bash
ollama serve &                # background daemon
ollama run llama3.2:3b "hi"   # warms the runtime intent model
ollama run llama3.1 "hi"      # only needed if re-running sentiment build
bash scripts/run_backend.sh   # FastAPI on :8000 (auto-reload, fast mode)
bash scripts/run_frontend.sh  # static server on :5500
```

Open `http://localhost:5500` and confirm the chat panel renders. Click
**New chat** to ensure you start clean. Have one extra terminal open in case
you want to demonstrate the Ollama-down fallback (Scenario 8).

---

## Scenario 1 — Cold start (conversational intent extraction)

**Prompt:**

```text
Hey, I'm a new BSCS student planning Fall 2026. Can you suggest classes?
```

**Point out:**
- The chat extracts `major="Bachelor of Science in Computer Science"` and
  `term="Fall 2026"` from a free-form English sentence — open the
  **Conversation state (debug)** dropdown to prove no form fields were used.
- Status line shows `intent: LLM` (vs. `intent: regex fallback`).
- The recommendation panel below the chat populates with three courses ranked
  by the multi-objective function.

**Proposal claim demonstrated:** Objective 1 (conversational interface) +
Objective 4 (multi-objective ranking).

---

## Scenario 2 — Prereq DAG (deterministic gating)

**Prompt (continue same chat):**

```text
I've already completed CSC 210, CSC 220, and MATH 226. Update my plan.
```

**Point out:**
- The reply ends with: *"Skipped N courses with unmet prereqs (deterministic
  check)."*
- Open the debug state — `completed_courses` updated.
- Expand a course card and read the **Prerequisites satisfied by:
  CSC 210, CSC 220** line.
- Tease the audience: *"Watch what happens if we forget MATH 226"* and reset
  to the next scenario.

**Proposal claim demonstrated:** Objective 2 (DAG-based prereq validation,
no LLM in the validation path).

---

## Scenario 3 — Sentiment-aware ranking (the headline feature)

Click **New chat**, then prompt:

```text
I'm a BSCS senior, planning Fall 2026. I've completed CSC 210, CSC 220,
CSC 230, CSC 256, CSC 340, CSC 415, MATH 226, MATH 227, MATH 245, PHYS 220.
I want an AI elective and I prefer professors with great reviews.
```

**Point out:**
- The course cards include **sentiment-scored professor blurbs** (green/red
  RMP tags such as "Amazing lectures" or "Tough grader").
- Each card shows a 1-2 sentence rationale generated for *this* student
  ("rationales: LLM" in the status line).
- Re-run with `prefer_high_rated_professors` flipped off (or with a different
  prompt that asks for "rigorous" classes) to show the order changing.

**Proposal claim demonstrated:** Objective 3 (sentiment integration) +
Objective 4 (multi-objective ranking with sentiment weight).

---

## Scenario 4 — Light workload preference

**Prompt:**

```text
Same situation but I'm working part-time, can you keep it under 9 units
and favor lighter classes?
```

**Point out:**
- `max_units_per_semester` becomes `9` in the state.
- `prefer_light_workload` flips to `true`.
- Total units in the schedule drops to ≤ 9.
- RMP `difficulty` values trend lower in the new selection.

**Proposal claim demonstrated:** Multi-objective ranking is genuinely
multi-objective — workload is not just a hard cap.

---

## Scenario 5 — Blocked time windows (constraint handling)

**Prompt:**

```text
I can't do anything before 11am on Mondays or Wednesdays.
```

**Point out:**
- Click **Blocked times** to reveal that the windows are now populated.
- The schedule grid on the right has no morning MoWe blocks.
- Any course that *only* offered MoWe morning sections got swapped out.

**Proposal claim demonstrated:** Real constraint satisfaction, not
LLM-imagined "vibes."

---

## Scenario 6 — Transcript paste (bulk parsing)

Paste a chunk of unofficial transcript text in a fresh chat:

```text
Here's my unofficial transcript, plan my Spring 2027:

Fall 2024
CSC 210  Introduction to Computer Programming  3.0  A
CSC 220  Data Structures                       3.0  B+
MATH 226 Calculus I                             4.0  A-

Spring 2025
CSC 230  Discrete Mathematical Structures      3.0  B
CSC 256  Machine Structures                    3.0  A
MATH 227 Calculus II                            4.0  B+

Fall 2025
CSC 340  Programming Methodology               3.0  A-
CSC 415  Operating System Principles           3.0  B+
MATH 245 Discrete Math for Computing           3.0  A
```

**Point out:**
- Debug state `transcript_text` populated with the raw paste.
- `completed_courses` auto-extracted from the transcript regex.
- Recommendations now reflect a junior-year student.

**Proposal claim demonstrated:** Practical UX — handles real student
artifacts, not just typed course codes.

---

## Scenario 7 — Different degree program (DSAI graduate)

New chat, prompt:

```text
I'm starting the MS DSAI program in Spring 2027, no graduate courses yet.
What should I take first?
```

**Point out:**
- Major resolves to
  `Master of Science in Data Science and Artificial Intelligence`.
- Recommendations come from a totally different requirement set
  (foundations + DSAI core).
- Confirms the system isn't hard-coded to BSCS.

**Proposal claim demonstrated:** Generalizes across degree programs from the
structured catalog.

---

## Scenario 8 — Failure mode / fallback (technical credibility moment)

In a side terminal, kill the LLM mid-demo:

```bash
pkill -f "ollama serve"
```

Then send:

```text
Plan my Fall 2026 BSCS schedule, I've finished CSC 210 and CSC 220.
```

**Point out:**
- Status line flips to `intent: regex fallback`.
- Reply still arrives in <1 second.
- Course cards still have rationales (now from the **pre-built template** in
  `course_descriptions.recommendation_rationale_template`, generated offline
  by `scripts/prebuild_demo_rationales.py`).
- Prereq checks still work — they never depended on the LLM.

Then restart Ollama:

```bash
ollama serve &
```

**Proposal claim demonstrated:** The LLM is an enhancement, not a single
point of failure. Critical for grading because the demo machine is CPU-only.

---

## Scenario 9 — Live "what if" (multi-turn state persistence)

Continuing any chat:

```text
What if I drop CSC 415 and replace it with something easier next semester?
```

**Point out:**
- The system keeps the rest of the state (major, term, completed courses,
  blocked times) and only re-ranks.
- Compare with the previous turn to show a diff.

**Proposal claim demonstrated:** Multi-turn coherent dialogue, not stateless
Q&A.

---

## Suggested 3-minute flow (8-min presentation slot)

Use this for the actual final presentation (8 min total = 5 min slides +
3 min demo). Run the **senior-year sentiment prompt from Scenario 3**, then
**blocked times from Scenario 5**, then **the Ollama-down fallback from
Scenario 8**. Skip the cold-start scenario — the senior-year prompt
demonstrates intent extraction in one shot and saves ~45 seconds.

| Beat | Time | What to point at |
|---|---:|---|
| Senior-year sentiment prompt (Scenario 3) | ~75s | green RMP tags, debug state, rationales |
| Blocked time windows (Scenario 5) | ~60s | empty MoWe morning grid |
| Kill Ollama, send another message (Scenario 8) | ~45s | status flips to `regex fallback`, plan still works |

## Suggested 5-minute flow

If you have 5 minutes (e.g. an open-house demo), run Scenarios
**1 → 3 → 5 → 8** in that order. Adds the cold-start moment.

## Suggested 10-minute flow

Add Scenarios **2 and 6** for deeper coverage of prereq validation and the
transcript-paste UX.

## Closing line for the audience

> "Every recommendation respects a deterministic prerequisite graph, every
> ranking blends sentiment with degree progress, and every line of
> conversation is parsed by a 3B-parameter model running locally on this
> laptop's CPU — no GPU, no API key, no cloud dependency."

---

## Rescue prompts (for when the LLM goes off-script)

If the small Llama 3.2 3B model misclassifies an intent, fall back to these
explicit prompts which the regex extractor handles deterministically:

```text
I am a BSCS student. Term: Fall 2026. Completed: CSC 210, CSC 220, MATH 226.
Prefer high-rated professors. Max units 12.
```

```text
I am an MSCS student. Term: Spring 2027. No completed graduate courses yet.
```

```text
Reset my completed courses and try again with just CSC 210.
```

These all hit the regex fallback cleanly even if Ollama is slow or down.
