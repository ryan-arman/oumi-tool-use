# google/gemma-4-E2B-it on τ² retail (test split): invalid run

> **Don't use these numbers as Gemma's score.** This run shared the tool server's stores with the claude-sonnet-5.5 run that came just before it (see "Why the run is invalid" below). The numbers are kept as a record and as a rough signal only. A clean rerun is pending.

Oumi evaluation 409 (operation 3597), run 2026-10-19.

## Setup

Same as the [claude-sonnet-5.5 run](../claude-sonnet-5.5/summary.md), except for the model under test:

| | |
|---|---|
| Model under test | `google/gemma-4-E2B-it` (PRETRAINED, served by Oumi on a GPU), temperature 0 |
| Simulated customer | `gpt-4.1`, temperature 0 |
| Max customer turns | 20 |
| Judges | `claude-sonnet-5.5`, temperature 0 |
| Dataset | τ²-bench retail test split, 40 tasks |

## Numbers (invalid run)

| Score | Result | claude-sonnet-5.5, for reference |
|---|---|---|
| τ² exact store match | 4/40 | 39/40 |
| Judge: Correct changes | 2/40 | 37/40 |
| Judge: Required statements | 35/40 | 40/40 |
| Tool calls | 238 in total, 1 to 14 per conversation (median 6) | 302 (median 7) |
| Refused tool calls | 24 | 4 |
| Customer turns | 4 to 13 per conversation (median 8); the customer ended all 40, none reached the limit | 4 to 10 (median 5) |
| Cost | $2.24 | $9.87 |
| Wall time | About 31 minutes, most of it starting the GPU before the first conversation | About 5 minutes |

Per-task detail is in `per_task.csv`, built by `summarize_results.py`.

## Why the run is invalid

The platform's session ID is the dataset row ID, so every evaluation of the same dataset reuses the same 40 session IDs. The tool server kept the claude-sonnet-5.5 run's stores in memory, and all 40 Gemma conversations continued on them. Orders Sonnet had already cancelled, exchanged or modified were no longer in their original state.

The refusals show it. Of the 24 refused calls:

- **16 say the order was already changed:** "Non-pending order cannot be …", "Non-delivered order …" or "There should be exactly one payment for a pending order". **15 of them hit an order that claude-sonnet-5.5 had changed in the same task**, across 12 tasks (9, 18, 32, 36, 40, 42, 55, 56, 60, 74, 77 and 108). For example, in task 18 Gemma tried to exchange items in order #W2890441, which Sonnet had already exchanged.
- **8 are "User / Order / Item not found".** Those are Gemma's own mistakes with IDs and don't depend on the shared stores.

The exact store match replays Gemma's calls on a fresh store, but Gemma chose those calls while looking at the changed stores. Neither the exact check nor the judges measure Gemma fairly here.

## What it still suggests

- **Tool-call format works.** Every tool call Gemma made was a proper structured call; none were written out as text.
- **Gemma is likely far behind Sonnet on this task.** It needed more customer turns, made more ID mistakes, and its "not found" refusals don't depend on the shared stores. Expect a clean run to score well below Sonnet. Measuring that gap is what the rerun is for.

## Next step

Rerun with the current `run_evaluation.py`, which gives each run its own URL and stores. See "Run isolation" in the top-level README and [LOU-4417](https://linear.app/oumi/issue/LOU-4417).
