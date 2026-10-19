"""Set up the tau2 retail multi-turn evaluation on the Oumi platform.

Creates, skipping anything that already exists by name:
  1. the evaluation dataset (uploaded from data/),
  2. the 16 retail tools (from data/tools.json),
  3. one endpoint implementation per tool, pointing at the tool server's
     default run (used for the test calls and manual checks; each evaluation
     gets its own implementations from run_evaluation.py),
  4. two judge evaluators (see evaluators.md),
then sends two test calls through the implementations and writes every id to
platform_ids.json.

Reads OUMI_API_KEY, OUMI_API_URL, OUMI_PROJECT_ID, TOOL_SERVER_API_KEY and
TOOL_SERVER_URL from the environment.

    ../.venv/bin/python setup_platform.py data/tau2_retail_test.jsonl
"""

import json
import os
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).parent
TOOLS_PATH = HERE / "data" / "tools.json"
IDS_PATH = HERE / "platform_ids.json"
IMPLEMENTATION_TIMEOUT_SECONDS = 30
UPLOAD_URL_EXPIRATION_SECONDS = 3600
OPERATION_POLL_SECONDS = 5
OPERATION_TIMEOUT_SECONDS = 600
JUDGE_MODEL = {"modelType": "ANTHROPIC_API", "modelName": "claude-sonnet-5.5"}
CHANGE_TOOLS = (
    "cancel_pending_order, exchange_delivered_order_items, "
    "modify_pending_order_address, modify_pending_order_items, "
    "modify_pending_order_payment, modify_user_address, "
    "return_delivered_order_items or transfer_to_human_agents"
)

EVALUATORS = [
    {
        "displayName": "tau2 retail - Correct changes",
        "description": "Whether the store changes the assistant made match the expected actions exactly (approximates tau2's store check).",
        "params": {
            "evaluatorType": "judge",
            "prompt": (
                "Evaluate whether the changes the assistant made to the store match "
                "the expected actions exactly.\n\n"
                "Judge 'Match' when every expected action appears as a tool call whose "
                "result is not an error, with the same tool and the same argument "
                "values. Compare every ID (order, item, payment method, user) "
                "character by character, and compare text values such as a "
                "cancellation reason exactly. Apart from the expected actions, the "
                f"assistant made no other successful call to {CHANGE_TOOLS}. Calls "
                "whose result is an error don't count either way. If the expected "
                "actions are 'None', judge 'Match' only when no such call succeeded.\n\n"
                "Judge 'Mismatch' in every other case: an expected action is missing, "
                "has any different argument value, or an extra change or transfer "
                "succeeded."
            ),
            "dataFields": {"expected_actions": "Expected actions"},
            "judgmentScores": {"Match": 1.0, "Mismatch": 0.0},
            "includeConversationSystem": False,
            "isMultiturn": True,
            "modelIdentifier": JUDGE_MODEL,
            "inferenceConfig": {"inferenceTemperature": 0.0},
        },
    },
    {
        "displayName": "tau2 retail - Required statements",
        "description": "Whether the assistant's messages satisfy every required statement (tau2's nl_assertions).",
        "params": {
            "evaluatorType": "judge",
            "prompt": (
                "Evaluate whether the assistant's messages to the user satisfy every "
                "required statement.\n\n"
                "Judge 'Pass' when every required statement holds for what the "
                "assistant told the user, or when the required statements are "
                "'None.'.\n\n"
                "Judge 'Fail' when at least one required statement does not hold."
            ),
            "dataFields": {"required_statements": "Required statements"},
            "judgmentScores": {"Pass": 1.0, "Fail": 0.0},
            "includeConversationSystem": False,
            "isMultiturn": True,
            "modelIdentifier": JUDGE_MODEL,
            "inferenceConfig": {"inferenceTemperature": 0.0},
        },
    },
]


class OumiClient:
    def __init__(self):
        self.base = f"{os.environ['OUMI_API_URL']}/projects/{os.environ['OUMI_PROJECT_ID']}"
        self.session = requests.Session()
        self.session.headers["X-API-Key"] = os.environ["OUMI_API_KEY"]

    def request(self, method: str, path: str, **kwargs) -> dict:
        response = self.session.request(method, f"{self.base}{path}", timeout=60, **kwargs)
        if not response.ok:
            raise RuntimeError(f"{method} {path} -> {response.status_code}: {response.text[:500]}")
        return response.json() if response.content else {}

    def list_all(self, path: str, key: str) -> list[dict]:
        items, token = [], None
        while True:
            params = {"pageSize": 100, **({"pageToken": token} if token else {})}
            page = self.request("GET", path, params=params)
            items.extend(page.get(key) or [])
            token = page.get("nextPageToken")
            if not token:
                return items


def upload_dataset(client: OumiClient, dataset_path: Path) -> int:
    display_name = dataset_path.stem
    for dataset in client.list_all("/datasets", "datasets"):
        if dataset["displayName"] == display_name:
            print(f"dataset exists: {display_name} (id {dataset['id']})")
            return dataset["id"]
    info = client.request(
        "POST",
        "/datasets:upload",
        json={
            "kind": "STANDARD",
            "displayName": display_name,
            "fileName": dataset_path.name,
            "fileSize": dataset_path.stat().st_size,
            "expiration": UPLOAD_URL_EXPIRATION_SECONDS,
        },
    )
    with dataset_path.open("rb") as file_handle:
        uploaded = requests.post(
            info["upload"]["uploadUrl"],
            data=info["upload"]["fields"],
            files={"file": (dataset_path.name, file_handle)},
            timeout=120,
        )
    if uploaded.status_code not in (200, 201, 204):
        raise RuntimeError(f"file upload failed: {uploaded.status_code} {uploaded.text[:300]}")
    operation_id = info["operation"]["id"]
    deadline = time.monotonic() + OPERATION_TIMEOUT_SECONDS
    while True:
        operation = client.request("GET", f"/operations/{operation_id}")
        status = operation["status"]
        if status == "completed":
            break
        if status in ("failed", "cancelled") or time.monotonic() > deadline:
            raise RuntimeError(f"dataset upload {status}: {json.dumps(operation)[:500]}")
        time.sleep(OPERATION_POLL_SECONDS)
    for dataset in client.list_all("/datasets", "datasets"):
        if dataset["displayName"] == display_name:
            print(f"dataset uploaded: {display_name} (id {dataset['id']})")
            return dataset["id"]
    raise RuntimeError("uploaded dataset not found in the dataset list")


def create_tools(client: OumiClient) -> dict[str, int]:
    existing = {tool["toolName"]: tool["id"] for tool in client.list_all("/tools", "tools")}
    tool_ids = {}
    for definition in json.loads(TOOLS_PATH.read_text()):
        function = definition["function"]
        name = function["name"]
        if name in existing:
            tool_ids[name] = existing[name]
            continue
        created = client.request(
            "POST",
            "/tools",
            json={
                "displayName": name,
                "toolName": name,
                "description": function["description"],
                "parameters": function["parameters"],
            },
        )
        tool_ids[name] = created["id"]
    print(f"tools ready: {len(tool_ids)} ({len(tool_ids) - len(existing.keys() & tool_ids.keys())} created)")
    return tool_ids


def endpoint_implementation_request(display_name: str, endpoint_url: str) -> dict:
    """Body for creating an endpoint implementation that calls the tool server."""
    return {
        "displayName": display_name,
        "config": {
            "type": "endpoint",
            "endpointUrl": endpoint_url,
            "timeoutSeconds": IMPLEMENTATION_TIMEOUT_SECONDS,
            "protocol": {"type": "http", "method": "POST"},
            "auth": {
                "type": "apiKey",
                "token": os.environ["TOOL_SERVER_API_KEY"],
                "headerName": "x-api-key",
            },
        },
    }


def create_implementations(client: OumiClient, tool_ids: dict[str, int]) -> dict[str, int]:
    server_url = os.environ["TOOL_SERVER_URL"].rstrip("/")
    implementation_ids = {}
    created_count = 0
    for name, tool_id in tool_ids.items():
        display_name = f"{name} - tau2 server"
        existing = client.list_all(f"/tools/{tool_id}/implementations", "toolImplementations")
        match = next((impl for impl in existing if impl["displayName"] == display_name), None)
        if match is not None:
            implementation_ids[name] = match["id"]
            continue
        created = client.request(
            "POST",
            f"/tools/{tool_id}/implementations",
            json=endpoint_implementation_request(display_name, f"{server_url}/tools/{name}"),
        )
        implementation_ids[name] = created["id"]
        created_count += 1
    print(f"implementations ready: {len(implementation_ids)} ({created_count} created)")
    return implementation_ids


def check_implementations(client, tool_ids, implementation_ids) -> None:
    checks = [
        ("find_user_id_by_name_zip", {"first_name": "Yusuf", "last_name": "Rossi", "zip": "19122"}),
        ("cancel_pending_order", {"order_id": "#W2378156", "reason": "no longer needed"}),
    ]
    for name, arguments in checks:
        result = client.request(
            "POST",
            f"/tools/{tool_ids[name]}/implementations/{implementation_ids[name]}:execute",
            json={"arguments": arguments, "sessionId": "setup-check"},
        )
        print(f"test call {name}: output={json.dumps(result.get('output'))} error={result.get('error')}")


def create_evaluators(client: OumiClient) -> dict[str, int]:
    existing = {e["displayName"]: e["id"] for e in client.list_all("/evaluators", "evaluators")}
    evaluator_ids = {}
    for evaluator in EVALUATORS:
        name = evaluator["displayName"]
        if name in existing:
            evaluator_ids[name] = existing[name]
            continue
        evaluator_ids[name] = client.request("POST", "/evaluators", json=evaluator)["id"]
    print(f"evaluators ready: {evaluator_ids}")
    return evaluator_ids


def main(dataset_path: str) -> None:
    client = OumiClient()
    dataset_id = upload_dataset(client, Path(dataset_path))
    tool_ids = create_tools(client)
    implementation_ids = create_implementations(client, tool_ids)
    check_implementations(client, tool_ids, implementation_ids)
    evaluator_ids = create_evaluators(client)
    IDS_PATH.write_text(
        json.dumps(
            {
                "dataset_id": dataset_id,
                "tool_ids": tool_ids,
                "implementation_ids": implementation_ids,
                "evaluator_ids": evaluator_ids,
                "tool_server_url": os.environ["TOOL_SERVER_URL"],
            },
            indent=2,
        )
    )
    print(f"wrote {IDS_PATH}")


if __name__ == "__main__":
    main(sys.argv[1])
