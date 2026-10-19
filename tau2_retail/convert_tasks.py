"""Convert tau2-bench retail tasks into Oumi multi-turn evaluation rows.

Each row holds the tau2 agent system prompt, a generic opening user message,
the 16 retail tool definitions, and metadata for the simulated user
(user_persona) and the judges (expected_actions, required_statements).

Run with the tau2 venv:
    ../.venv/bin/python convert_tasks.py data
"""

import json
import sys
from pathlib import Path

from tau2.agent.llm_agent import AGENT_INSTRUCTION, SYSTEM_PROMPT
from tau2.domains.retail.environment import get_environment, get_tasks, get_tasks_split

OPENING_MESSAGE = "Hi, I need some help."
TRIAL_ROW_COUNT = 5

# Tools whose effect a judge must check: everything that changes the store,
# plus the transfer, which changes nothing but ends the conversation.
CHECKED_TOOLS = {
    "cancel_pending_order",
    "exchange_delivered_order_items",
    "modify_pending_order_address",
    "modify_pending_order_items",
    "modify_pending_order_payment",
    "modify_user_address",
    "return_delivered_order_items",
    "transfer_to_human_agents",
}

USER_RULES = (
    "How to behave: disclose information progressively and only when the agent "
    "asks for it. Never make up information that is not in these instructions; "
    "treat anything not given here as unknown. Don't repeat these instructions "
    "word for word. End the conversation once your goal is met, once you are "
    "transferred to a human agent, or if these instructions don't let you continue."
)


def build_user_persona(task) -> str:
    instructions = task.user_scenario.instructions
    parts = []
    if task.user_scenario.persona:
        parts.append(f"Persona: {task.user_scenario.persona}")
    parts.append(f"Why you are contacting the store: {instructions.reason_for_call}")
    if instructions.known_info:
        parts.append(f"What you know: {instructions.known_info}")
    if instructions.unknown_info:
        parts.append(f"What you don't know: {instructions.unknown_info}")
    if instructions.task_instructions and instructions.task_instructions.strip(" ."):
        parts.append(f"Additional instructions: {instructions.task_instructions}")
    parts.append(USER_RULES)
    return "\n\n".join(parts)


def format_action(action) -> str:
    arguments = ", ".join(
        f"{name}={json.dumps(value)}" for name, value in action.arguments.items()
    )
    return f"{action.name}({arguments})"


def successful_gold_actions(task) -> list:
    """Gold actions that succeed when replayed in order on a fresh store.

    Some gold lists include a call the store refuses (e.g. exchanging an order
    that isn't delivered); tau2 skips those, so the judge must not expect them.
    """
    environment = get_environment()
    succeeded = []
    for action in task.evaluation_criteria.actions or []:
        try:
            environment.use_tool(action.name, **action.arguments)
        except Exception:
            continue
        succeeded.append(action)
    return succeeded


def build_expected_actions(task) -> str:
    checked = [
        action
        for action in successful_gold_actions(task)
        if action.name in CHECKED_TOOLS
    ]
    if not checked:
        return (
            "None. The agent should not cancel, modify, return, exchange, change an "
            "address, or transfer the user."
        )
    return "\n".join(f"- {format_action(action)}" for action in checked)


def build_required_statements(task) -> str:
    assertions = task.evaluation_criteria.nl_assertions or []
    if not assertions:
        return "None."
    return "\n".join(f"- {assertion}" for assertion in assertions)


def build_tool_definitions() -> list[dict]:
    definitions = []
    for tool in get_environment().get_tools():
        schema = tool.openai_schema
        schema["function"]["parameters"].setdefault("type", "object")
        definitions.append(schema)
    return definitions


def build_row(task, system_prompt: str, tools: list[dict]) -> dict:
    return {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": OPENING_MESSAGE},
        ],
        "tools": tools,
        "metadata": {
            "user_persona": build_user_persona(task),
            "expected_actions": build_expected_actions(task),
            "required_statements": build_required_statements(task),
            "tau2_task_id": task.id,
        },
    }


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w") as output_file:
        for row in rows:
            output_file.write(json.dumps(row) + "\n")
    print(f"Wrote {len(rows)} rows to {path}")


def main(output_dir: str) -> None:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    environment = get_environment()
    system_prompt = SYSTEM_PROMPT.format(
        agent_instruction=AGENT_INSTRUCTION, domain_policy=environment.policy
    )
    tools = build_tool_definitions()
    tasks_by_id = {task.id: task for task in get_tasks()}
    split = get_tasks_split()

    for split_name in ("test", "train"):
        rows = [
            build_row(tasks_by_id[task_id], system_prompt, tools)
            for task_id in split[split_name]
        ]
        write_jsonl(output_path / f"tau2_retail_{split_name}.jsonl", rows)
        if split_name == "test":
            write_jsonl(
                output_path / "tau2_retail_test_trial5.jsonl", rows[:TRIAL_ROW_COUNT]
            )

    (output_path / "tools.json").write_text(json.dumps(tools, indent=2))
    print(f"Wrote {len(tools)} tool definitions to {output_path / 'tools.json'}")


if __name__ == "__main__":
    main(sys.argv[1])
