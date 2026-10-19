"""Summarize the tool server's call log (logs/calls.jsonl).

Calls logged before per-run isolation have no run id and count as the
"default" run.

    python3 call_stats.py                         # calls per run, then a summary of all runs
    python3 call_stats.py --run <run_tag>         # summary of one run
    python3 call_stats.py --session <prefix>      # every call one conversation made, in order
"""

import argparse
import collections
import json
from pathlib import Path

LOG_PATH = Path(__file__).parent / "logs" / "calls.jsonl"
DEFAULT_RUN_ID = "default"
MANUAL_SESSIONS = {"setup-check", "run-check", "logs-check", "me", "me-debug", "other"}
CHANGE_TOOLS = {
    "cancel_pending_order",
    "exchange_delivered_order_items",
    "modify_pending_order_address",
    "modify_pending_order_items",
    "modify_pending_order_payment",
    "modify_user_address",
    "return_delivered_order_items",
    "transfer_to_human_agents",
}


def load_calls() -> list[dict]:
    calls = [json.loads(line) for line in LOG_PATH.open() if line.strip()]
    for call in calls:
        call.setdefault("run_id", DEFAULT_RUN_ID)
    return calls


def print_runs(calls: list[dict]) -> None:
    per_run = collections.Counter(call["run_id"] for call in calls)
    print("calls per run:")
    for run_id, count in per_run.items():
        print(f"  {run_id:40} {count}")
    print()


def print_session(calls: list[dict], session_prefix: str) -> None:
    for call in calls:
        if call["session_id"].startswith(session_prefix):
            outcome = "ok" if call["status"] == 200 else f"REFUSED ({call['status']})"
            print(f"[{call['run_id']}] {call['tool']}({json.dumps(call['arguments'])}) -> {outcome}")


def print_summary(calls: list[dict]) -> None:
    evaluation_calls = [
        c
        for c in calls
        if c["session_id"] not in MANUAL_SESSIONS and not c["session_id"].startswith("smoke")
    ]
    conversations = collections.Counter((c["run_id"], c["session_id"]) for c in evaluation_calls)
    print(f"evaluation calls: {len(evaluation_calls)} from {len(conversations)} conversations")
    if conversations:
        counts = sorted(conversations.values())
        print(f"calls per conversation: min {counts[0]}, median {counts[len(counts) // 2]}, max {counts[-1]}")
    by_tool = collections.defaultdict(lambda: [0, 0])
    for call in evaluation_calls:
        by_tool[call["tool"]][0 if call["status"] == 200 else 1] += 1
    print("\ncalls by tool (ok / refused):")
    for tool, (ok, refused) in sorted(by_tool.items(), key=lambda item: -sum(item[1])):
        print(f"  {tool:32} {ok:4} / {refused}")
    print("\nrefused calls:")
    for call in evaluation_calls:
        if call["status"] != 200:
            print(f"  [{call['run_id']}] {call['session_id'][:14]}  {call['tool']}({json.dumps(call['arguments'])})")
    print("\nsuccessful changes per conversation:")
    changes = collections.defaultdict(list)
    for call in evaluation_calls:
        if call["tool"] in CHANGE_TOOLS and call["status"] == 200:
            changes[(call["run_id"], call["session_id"])].append(call["tool"])
    for run_id, session_id in conversations:
        print(f"  [{run_id}] {session_id[:14]}  {', '.join(changes.get((run_id, session_id), [])) or '(none)'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--run", help="only this run")
    parser.add_argument("--session", help="print one conversation's calls (session id prefix)")
    args = parser.parse_args()
    all_calls = load_calls()
    if args.run:
        all_calls = [call for call in all_calls if call["run_id"] == args.run]
    if args.session:
        print_session(all_calls, args.session)
    else:
        if not args.run:
            print_runs(all_calls)
        print_summary(all_calls)
