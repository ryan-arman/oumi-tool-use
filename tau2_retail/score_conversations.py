"""Score conversations with tau2-bench's exact store check.

For each conversation, replays the agent's tool calls on a fresh retail store
and compares the result with replaying the task's correct actions. A match is
tau2's database reward of 1.

Input is a JSONL file of rows with OpenAI-style "messages" (assistant messages
carrying "tool_calls") and the task id in metadata.tau2_task_id.

Run with the tau2 venv:
    ../.venv/bin/python score_conversations.py <conversations.jsonl>
"""

import json
import sys
from dataclasses import dataclass

from tau2.domains.retail.environment import get_environment, get_tasks


@dataclass
class ConversationScore:
    task_id: str
    db_match: bool
    tool_calls: int
    failed_calls: int


def gold_db_hash(task) -> str:
    environment = get_environment()
    for action in task.evaluation_criteria.actions or []:
        # Some tau2 gold lists include calls that fail (e.g. a lookup with an
        # item id); tau2's own evaluator skips them, so this does too.
        try:
            environment.use_tool(action.name, **action.arguments)
        except Exception:
            pass
    return environment.get_db_hash()


def agent_tool_calls(messages: list[dict]) -> list[tuple[str, dict]]:
    calls = []
    for message in messages:
        if message.get("role") != "assistant":
            continue
        # OpenAI-style rows use tool_calls; Oumi evaluation results use toolCalls.
        for tool_call in message.get("tool_calls") or message.get("toolCalls") or []:
            function = tool_call["function"]
            arguments = function.get("arguments") or {}
            if isinstance(arguments, str):
                arguments = json.loads(arguments) if arguments.strip() else {}
            calls.append((function["name"], arguments))
    return calls


def score_row(row: dict, tasks_by_id: dict) -> ConversationScore:
    task_id = str(row["metadata"]["tau2_task_id"])
    environment = get_environment()
    calls = agent_tool_calls(row["messages"])
    failed_calls = 0
    for name, arguments in calls:
        try:
            environment.use_tool(name, **arguments)
        except Exception:
            failed_calls += 1
    return ConversationScore(
        task_id=task_id,
        db_match=environment.get_db_hash() == gold_db_hash(tasks_by_id[task_id]),
        tool_calls=len(calls),
        failed_calls=failed_calls,
    )


def main(conversations_path: str) -> None:
    tasks_by_id = {task.id: task for task in get_tasks()}
    scores = [
        score_row(json.loads(line), tasks_by_id)
        for line in open(conversations_path)
        if line.strip()
    ]
    for score in scores:
        print(
            f"task {score.task_id:>4}: {'PASS' if score.db_match else 'FAIL'} "
            f"({score.tool_calls} tool calls, {score.failed_calls} refused)"
        )
    passed = sum(score.db_match for score in scores)
    print(f"\nExact store match: {passed}/{len(scores)} = {passed / len(scores):.1%}")


if __name__ == "__main__":
    main(sys.argv[1])
