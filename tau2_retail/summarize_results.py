"""Write per_task.csv and exact_scores.txt for one model's results folder.

Reads <results_dir>/conversations.jsonl (written by export_results.py), runs
tau2's exact store check on every conversation, and prints the headline numbers.

    ../.venv/bin/python summarize_results.py results/claude-sonnet-5.5
"""

import csv
import json
import sys
from pathlib import Path

from tau2.domains.retail.environment import get_tasks

from score_conversations import score_row

CORRECT_CHANGES_JUDGE = "tau2 retail - Correct changes"
REQUIRED_STATEMENTS_JUDGE = "tau2 retail - Required statements"
REFUSAL_PREFIX = "Endpoint returned HTTP 4"
COLUMNS = [
    "tau2_task_id",
    "exact_store_match",
    "judge_correct_changes",
    "judge_required_statements",
    "user_turns",
    "tool_calls",
    "refused_tool_calls",
    "expected_actions",
]


def summarize_row(row: dict, tasks_by_id: dict) -> dict:
    messages = row["messages"]
    judges = row["metadata"].get("judge") or {}
    score = score_row(row, tasks_by_id)
    return {
        "tau2_task_id": score.task_id,
        "exact_store_match": "PASS" if score.db_match else "FAIL",
        "judge_correct_changes": judges.get(CORRECT_CHANGES_JUDGE, ""),
        "judge_required_statements": judges.get(REQUIRED_STATEMENTS_JUDGE, ""),
        "user_turns": sum(message["role"] == "user" for message in messages),
        "tool_calls": score.tool_calls,
        "refused_tool_calls": sum(
            message["role"] == "tool"
            and (message.get("content") or "").startswith(REFUSAL_PREFIX)
            for message in messages
        ),
        "expected_actions": " | ".join(
            line.removeprefix("- ")
            for line in row["metadata"]["expected_actions"].splitlines()
        ),
    }


def main(results_dir: str) -> None:
    results_path = Path(results_dir)
    tasks_by_id = {task.id: task for task in get_tasks()}
    rows = [
        json.loads(line)
        for line in (results_path / "conversations.jsonl").open()
        if line.strip()
    ]
    summaries = sorted(
        (summarize_row(row, tasks_by_id) for row in rows),
        key=lambda summary: int(summary["tau2_task_id"]),
    )

    with (results_path / "per_task.csv").open("w", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(summaries)

    passed = sum(s["exact_store_match"] == "PASS" for s in summaries)
    with (results_path / "exact_scores.txt").open("w") as scores_file:
        for s in summaries:
            scores_file.write(
                f"task {s['tau2_task_id']:>4}: {s['exact_store_match']} "
                f"({s['tool_calls']} tool calls, {s['refused_tool_calls']} refused)\n"
            )
        scores_file.write(
            f"\nExact store match: {passed}/{len(summaries)} = {passed / len(summaries):.1%}\n"
        )

    def count(column: str, value: str) -> int:
        return sum(s[column] == value for s in summaries)

    turns = sorted(s["user_turns"] for s in summaries)
    calls = sorted(s["tool_calls"] for s in summaries)
    print(f"exact store match:   {passed}/{len(summaries)}")
    print(f"correct changes:     {count('judge_correct_changes', 'Match')}/{len(summaries)}")
    print(f"required statements: {count('judge_required_statements', 'Pass')}/{len(summaries)}")
    print(f"tool calls: {sum(calls)} total, {calls[0]}-{calls[-1]} per conversation (median {calls[len(calls) // 2]})")
    print(f"refused tool calls: {sum(s['refused_tool_calls'] for s in summaries)}")
    print(f"customer turns: {turns[0]}-{turns[-1]} (median {turns[len(turns) // 2]})")


if __name__ == "__main__":
    main(sys.argv[1])
