"""Start a multi-turn tau2 retail evaluation on Oumi for one model.

Each run gets its own run tag and its own 16 endpoint implementations pointing
at /runs/<tag>/tools/<tool> on the tool server, so its conversations get fresh
stores even though Oumi reuses the dataset's session ids in every evaluation
(see tool_server.py). Before launching, one test call goes through the new
implementations to check that the tunnel and server answer on the run's URL.
The run is recorded in runs.json; cleanup_run.py deletes its implementations
once the evaluation has finished.

Uses the dataset, tools and evaluators recorded in platform_ids.json by
setup_platform.py. The simulated customer matches tau2-bench's default (gpt-4.1
at temperature 0).

Reads OUMI_API_KEY, OUMI_API_URL, OUMI_PROJECT_ID, TOOL_SERVER_API_KEY and
TOOL_SERVER_URL from the environment, and OUMI_WEB_URL if set (to print a link
to the evaluations page).

    ../.venv/bin/python run_evaluation.py ANTHROPIC_API claude-sonnet-5.5
    ../.venv/bin/python run_evaluation.py PRETRAINED google/gemma-4-E2B-it
    ../.venv/bin/python run_evaluation.py PRETRAINED google/gemma-4-E2B-it --no-launch
"""

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from setup_platform import OumiClient, endpoint_implementation_request

HERE = Path(__file__).parent
IDS_PATH = HERE / "platform_ids.json"
RUNS_PATH = HERE / "runs.json"
USER_MODEL = {"modelType": "OPENAI_API", "modelName": "gpt-4.1"}
TEMPERATURE = 0.0
MAX_USER_TURNS = 20
MAX_MODEL_SLUG_LENGTH = 40
CHECK_TOOL = "find_user_id_by_name_zip"
CHECK_ARGUMENTS = {"first_name": "Yusuf", "last_name": "Rossi", "zip": "19122"}
CHECK_EXPECTED_OUTPUT = "yusuf_rossi_9620"
CHECK_SESSION_ID = "run-check"


def load_runs() -> dict:
    return json.loads(RUNS_PATH.read_text()) if RUNS_PATH.exists() else {}


def save_runs(runs: dict) -> None:
    RUNS_PATH.write_text(json.dumps(runs, indent=2))


def make_run_tag(model_name: str) -> str:
    slug = re.sub(r"[^a-z0-9.-]+", "-", model_name.split("/")[-1].lower()).strip("-")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{slug[:MAX_MODEL_SLUG_LENGTH]}-{timestamp}"


def create_run_implementations(
    client: OumiClient, tool_ids: dict[str, int], run_tag: str
) -> dict[str, int]:
    server_url = os.environ["TOOL_SERVER_URL"].rstrip("/")
    implementation_ids = {}
    for name, tool_id in tool_ids.items():
        created = client.request(
            "POST",
            f"/tools/{tool_id}/implementations",
            json=endpoint_implementation_request(
                f"{name} - run {run_tag}", f"{server_url}/runs/{run_tag}/tools/{name}"
            ),
        )
        implementation_ids[name] = created["id"]
    return implementation_ids


def delete_implementations(
    client: OumiClient, tool_ids: dict[str, int], implementation_ids: dict[str, int]
) -> None:
    for name, implementation_id in implementation_ids.items():
        client.request(
            "DELETE", f"/tools/{tool_ids[name]}/implementations/{implementation_id}"
        )


def check_run_endpoint(
    client: OumiClient, tool_ids: dict[str, int], implementation_ids: dict[str, int]
) -> str | None:
    """Send one call through the run's implementations; return an error or None."""
    result = client.request(
        "POST",
        f"/tools/{tool_ids[CHECK_TOOL]}/implementations/{implementation_ids[CHECK_TOOL]}:execute",
        json={"arguments": CHECK_ARGUMENTS, "sessionId": CHECK_SESSION_ID},
    )
    if result.get("output") == CHECK_EXPECTED_OUTPUT:
        return None
    return f"output={json.dumps(result.get('output'))} error={result.get('error')}"


def evaluation_request(
    ids: dict, model_type: str, model_name: str, run_tag: str, implementation_ids: dict
) -> dict:
    return {
        "displayName": f"tau2 retail test - {model_name} - run {run_tag}",
        "recipe": {
            "recipeConfig": {
                "type": "evaluate",
                "evaluationConfig": {
                    "evaluationType": "single_model",
                    "modelIdentifier": {"modelType": model_type, "modelName": model_name},
                    "evaluators": [
                        {"evaluatorId": evaluator_id}
                        for evaluator_id in ids["evaluator_ids"].values()
                    ],
                    "inferenceConfig": {"inferenceTemperature": TEMPERATURE},
                    "dataset": {"datasetId": ids["dataset_id"]},
                    "generateFailureModes": False,
                    "agenticInferenceConfig": {
                        "toolImplementations": [
                            {"toolImplementationId": implementation_id}
                            for implementation_id in implementation_ids.values()
                        ],
                        "userModelSpec": {
                            "modelIdentifier": USER_MODEL,
                            "inferenceConfig": {"inferenceTemperature": TEMPERATURE},
                        },
                        "maxUserTurns": MAX_USER_TURNS,
                    },
                },
            }
        },
    }


def main(model_type: str, model_name: str, launch: bool) -> None:
    ids = json.loads(IDS_PATH.read_text())
    tool_ids = ids["tool_ids"]
    client = OumiClient()
    run_tag = make_run_tag(model_name)

    implementation_ids = create_run_implementations(client, tool_ids, run_tag)
    print(f"run {run_tag}: created {len(implementation_ids)} implementations")
    check_error = check_run_endpoint(client, tool_ids, implementation_ids)
    if check_error is not None:
        delete_implementations(client, tool_ids, implementation_ids)
        raise SystemExit(
            f"test call through the run's URL failed ({check_error}); deleted the "
            "run's implementations. Is the tool server running the current "
            "tool_server.py, and is TOOL_SERVER_URL the live tunnel?"
        )
    print("test call through the run's URL: ok")

    runs = load_runs()
    runs[run_tag] = {
        "model_type": model_type,
        "model_name": model_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tool_server_url": os.environ["TOOL_SERVER_URL"],
        "implementation_ids": implementation_ids,
        "operation_id": None,
    }
    save_runs(runs)
    if not launch:
        print(f"not launched (--no-launch); delete with: cleanup_run.py {run_tag}")
        return

    operation = client.request(
        "POST",
        "/evaluations:run",
        json=evaluation_request(ids, model_type, model_name, run_tag, implementation_ids),
    )
    runs[run_tag]["operation_id"] = operation["id"]
    save_runs(runs)
    print(f"run {run_tag}: evaluation operation {operation['id']} ({operation['status']})")
    web_url = os.environ.get("OUMI_WEB_URL", "").rstrip("/")
    if web_url:
        project_id = os.environ["OUMI_PROJECT_ID"]
        org_id = project_id.split("-")[0]
        print(f"Evaluations page: {web_url}/workspace/{org_id}/{project_id}/evaluations")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("model_type", help="e.g. ANTHROPIC_API, OPENAI_API, PRETRAINED")
    parser.add_argument("model_name", help="e.g. claude-sonnet-5.5, google/gemma-4-E2B-it")
    parser.add_argument(
        "--no-launch",
        action="store_true",
        help="create and check the run's implementations without starting the evaluation",
    )
    args = parser.parse_args()
    main(args.model_type, args.model_name, launch=not args.no_launch)
