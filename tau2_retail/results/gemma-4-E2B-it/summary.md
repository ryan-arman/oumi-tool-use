# google/gemma-4-E2B-it on τ² retail (test split)

Oumi evaluation 410 (operation 3598), run 2026-10-19, on a clean tool server. The first Gemma run (evaluation 409) was invalid and is kept in `invalid-run-3597/`.

## Setup

Same as the [claude-sonnet-5.5 run](../claude-sonnet-5.5/summary.md), except for the model under test:

| | |
|---|---|
| Model under test | `google/gemma-4-E2B-it` (PRETRAINED, served by Oumi on a GPU), temperature 0 |
| Simulated customer | `gpt-4.1`, temperature 0 |
| Max customer turns | 20 |
| Judges | `claude-sonnet-5.5`, temperature 0 |
| Dataset | τ²-bench retail test split, 40 tasks |

## Headline numbers

| Score | gemma-4-E2B-it | claude-sonnet-5.5 |
|---|---|---|
| τ² exact store match | **16/40 (40%)** | 39/40 (97.5%) |
| Judge: Correct changes | 15/40 | 37/40 |
| Judge: Required statements | 37/40 | 40/40 |
| Tool calls | 270, 2 to 14 per conversation (median 6) | 302 (median 7) |
| Refused tool calls | 19 | 4 |
| Customer turns | 5 to 14 (median 8); none reached the limit | 4 to 10 (median 5) |
| Cost | $2.41 | $9.87 |
| Wall time | About 27 minutes, much of it starting the GPU | About 5 minutes |

Gemma passes 16 tasks: 15 that Sonnet also passes, plus task 12, the one Sonnet failed. Sonnet passes all 24 tasks Gemma fails.

Per-task detail is in `per_task.csv`, built by `summarize_results.py`.

## Where Gemma fails

| What went wrong | Tasks | Count |
|---|---|---|
| Transferred to a human instead of making the change itself | 9, 17, 27, 74, 77, 90, 100, 101, 111 | 9 |
| Changed the wrong order, or used the wrong action | 36, 56, 70, 71, 94 | 5 |
| Made no change and didn't transfer | 5, 39, 45 | 3 |
| Made some of the required changes but missed or added others | 32, 97, 102 | 3 |
| Right action on the right order, wrong details (item, payment method, address or reason) | 38, 42, 49 | 3 |
| Made a change when none was expected | 62 | 1 |

**The biggest pattern is giving up too early.** Instead of looking up details the customer doesn't have, Gemma transfers them to a human. Two examples:

- **Task 17:** the customer wants order #W8665881 delivered to Suite 641. Gemma found the customer, then transferred because "the user is unable to provide full address details". The fix only needed the order's current address with the suite changed.
- **Task 74:** Gemma checked two of the customer's orders, then transferred because the customer couldn't recall an order ID. The right move was to check the rest of the customer's orders.

**Refused calls (19)** were all Gemma's own mistakes this time, since every conversation started from a clean store:

- **8 lookups with details that didn't match:** "User not found" (6) and "Order not found" (2).
- **6 changes on an order in the wrong state:** "Non-pending order cannot be …" (3) and "Non-delivered order …" (3).
- **5 changes with invalid details:** an item variant that doesn't exist (3), a payment method that isn't allowed (1), and a wrong number of items (1).

**Judges:** "Correct changes" agrees with the exact check on 39 of 40 tasks. The one difference is task 26, the same as for Sonnet: the correct return was made but no transfer, which the judge counts and the store check doesn't. The 3 "Required statements" failures (39, 45, 111) are conversations where Gemma made no change or transferred.

## What this means for training

- **Tool-call formatting isn't the problem.** Every call Gemma made was a proper structured call.
- **The gap is in decisions:** when to look things up instead of asking or transferring, which order a request refers to, and getting item and payment details right.
- **Sonnet's conversations are the training targets.** Sonnet passes all 24 tasks Gemma fails, so its successful conversations on the same kind of task are what fine-tuning should teach.

## Caveats

This is a single run, with the same simulated-customer caveats as the Sonnet run: it runs inside Oumi rather than τ²'s own harness, and every conversation opens with a generic message.
