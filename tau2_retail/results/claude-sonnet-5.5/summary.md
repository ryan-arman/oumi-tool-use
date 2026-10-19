# claude-sonnet-5.5 on τ² retail (test split)

Oumi evaluation, run 2026-10-19.

## Setup

| | |
|---|---|
| Model under test | `claude-sonnet-5.5` (ANTHROPIC_API), temperature 0 |
| Simulated customer | `gpt-4.1`, temperature 0 (τ²-bench's default) |
| Max customer turns | 20 |
| Judges | `claude-sonnet-5.5`, temperature 0 (see `../../evaluators.md`) |
| Dataset | τ²-bench retail test split, 40 tasks (`../../data/tau2_retail_test.jsonl`) |
| Tools | The 16 τ² retail tools, run by τ²'s own code through `tool_server.py`, with one fresh store per conversation |

## Headline numbers

| Score | Result |
|---|---|
| τ² exact store match | **39/40 (97.5%)** |
| Judge: Correct changes | 37/40 (92.5%) |
| Judge: Required statements | 40/40 (100%); 11 of the 40 tasks have statements to check |
| Cost | $9.87 |
| Wall time | About 5 minutes |
| Tool calls | 302 in total, 3 to 13 per conversation (median 7) |
| Refused tool calls | 4, all customer lookups with a wrong email or zip; the agent recovered each time |
| Customer turns | 4 to 10 per conversation (median 5); none reached the 20-turn limit |

Per-task detail is in `per_task.csv`. `exact_scores.txt` is the output of `score_conversations.py`. `conversations.jsonl` holds the 40 conversations, with the judge verdicts in each row's metadata.

## The one real failure

**Task 12.** The customer wants refunds to PayPal, which the store can't do, so the correct action is a transfer to a human agent. The model processed a return to the customer's credit card instead. Both the exact check and the judge fail it.

## Where the judge and the exact check disagree

The "Correct changes" judge reads `expected_actions`, which includes `transfer_to_human_agents` whenever τ²'s list of correct actions does. τ²'s exact check compares only the final store, and a transfer doesn't change the store.

- **Task 26:** the model made the correct return but didn't transfer. Exact: PASS. Judge: Mismatch.
- **Task 36:** the model made the correct item change, then also transferred. Exact: PASS. Judge: Mismatch.

In both cases the judge applied its instructions correctly. The difference is only whether transfers count.

## Caveats

This is a single run. The simulated customer runs inside Oumi rather than τ²'s own harness, and every conversation opens with the same generic message ("Hi, I need some help.") instead of one the customer writes. Treat these numbers as a baseline for this setup, not as directly comparable to the τ² leaderboard.
