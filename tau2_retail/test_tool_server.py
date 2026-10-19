"""Check the tool server against tau2-bench's own answers.

For every retail task, replays the task's correct actions through the HTTP API
in its own session and checks the session's store hash equals tau2's gold hash.
Also checks auth, refusals, session and run isolation, and unknown tools.

Run with the tau2 venv (TOOL_SERVER_API_KEY must be set):
    ../.venv/bin/python test_tool_server.py
"""

import os

from fastapi.testclient import TestClient
from tau2.domains.retail.environment import get_tasks

from score_conversations import gold_db_hash
from tool_server import app

client = TestClient(app)
HEADERS = {"x-api-key": os.environ["TOOL_SERVER_API_KEY"]}


def call(
    tool: str,
    arguments: dict,
    session_id: str,
    headers: dict = HEADERS,
    run_id: str | None = None,
):
    path = f"/runs/{run_id}/tools/{tool}" if run_id else f"/tools/{tool}"
    return client.post(
        path, json=arguments, headers={**headers, "X-Oumi-Session-Id": session_id}
    )


def check_run_isolation() -> None:
    """The same session id in two runs and the default run gets three stores."""
    pending_order = "#W4776164"
    session_id = "same-row-id"
    cancelled = call(
        "cancel_pending_order",
        {"order_id": pending_order, "reason": "no longer needed"},
        session_id,
        run_id="run-a",
    )
    assert cancelled.status_code == 200, cancelled.text

    def status_in(run_id: str | None) -> str:
        response = call("get_order_details", {"order_id": pending_order}, session_id, run_id=run_id)
        return response.json()["status"]

    assert status_in("run-a") == "cancelled"
    assert status_in("run-b") == "pending"
    assert status_in(None) == "pending"

    hash_a = client.get(f"/runs/run-a/sessions/{session_id}/db_hash", headers=HEADERS)
    hash_b = client.get(f"/runs/run-b/sessions/{session_id}/db_hash", headers=HEADERS)
    hash_default = client.get(f"/sessions/{session_id}/db_hash", headers=HEADERS)
    assert hash_a.json()["db_hash"] != hash_b.json()["db_hash"]
    assert hash_b.json()["db_hash"] == hash_default.json()["db_hash"]

    bad_run = call("get_order_details", {"order_id": pending_order}, session_id, run_id="bad run!")
    assert bad_run.status_code in (400, 404), bad_run.text
    print("run isolation: run-a sees its cancel; run-b and the default run do not")


def check_gold_replays() -> None:
    mismatches = []
    refused_gold_calls = []
    tasks = get_tasks()
    for task in tasks:
        session_id = f"gold-{task.id}"
        # A read opens the session, so tasks with no gold actions have one too.
        call("list_all_product_types", {}, session_id)
        for action in task.evaluation_criteria.actions or []:
            response = call(action.name, action.arguments, session_id)
            assert response.status_code in (200, 400), (task.id, response.text)
            if response.status_code == 400:
                refused_gold_calls.append((task.id, action.name, response.json()))
        served_hash = client.get(
            f"/sessions/{session_id}/db_hash", headers=HEADERS
        ).json()["db_hash"]
        if served_hash != gold_db_hash(task):
            mismatches.append(task.id)
    print(f"gold calls refused (tau2 skips these too): {refused_gold_calls}")
    print(f"gold replays matching tau2: {len(tasks) - len(mismatches)}/{len(tasks)}")
    assert not mismatches, mismatches


def check_edge_cases() -> None:
    no_key = call("get_order_details", {"order_id": "#W2378156"}, "s1", headers={})
    assert no_key.status_code == 401, no_key.text

    refused = call(
        "cancel_pending_order",
        {"order_id": "#W2378156", "reason": "no longer needed"},
        "s1",
    )
    assert refused.status_code == 400, refused.text
    print("refusal body:", refused.json())

    unknown = call("delete_everything", {}, "s1")
    assert unknown.status_code == 404, unknown.text

    pending_order = "#W4776164"
    before = call("get_order_details", {"order_id": pending_order}, "s2").json()
    assert before["status"] == "pending", before["status"]
    cancelled = call(
        "cancel_pending_order",
        {"order_id": pending_order, "reason": "no longer needed"},
        "s2",
    )
    assert cancelled.status_code == 200, cancelled.text
    after_same = call("get_order_details", {"order_id": pending_order}, "s2").json()
    after_other = call("get_order_details", {"order_id": pending_order}, "s3").json()
    assert after_same["status"] == "cancelled", after_same["status"]
    assert after_other["status"] == "pending", after_other["status"]
    print("session isolation: same session sees cancel, other session does not")

    plain = call(
        "find_user_id_by_name_zip",
        {"first_name": "Yusuf", "last_name": "Rossi", "zip": "19122"},
        "s4",
    )
    print("string output body:", plain.text)


if __name__ == "__main__":
    check_edge_cases()
    check_run_isolation()
    check_gold_replays()
    print("all checks passed")
