"""Download a finished Oumi evaluation's results for exact scoring.

Given the operation id that run_evaluation.py printed, writes to <output_dir>:
  oumi_dataitems.json  the raw results from the platform
  conversations.jsonl  one row per conversation, in the format
                       score_conversations.py reads, with the judge verdicts
                       added to each row's metadata

Reads OUMI_API_KEY, OUMI_API_URL and OUMI_PROJECT_ID from the environment.

    ../.venv/bin/python export_results.py 3596 results/claude-sonnet-5.5
    ../.venv/bin/python score_conversations.py results/claude-sonnet-5.5/conversations.jsonl
"""

import json
import os
import sys
from pathlib import Path

import requests

PAGE_SIZE = 100


def get(session: requests.Session, path: str, **params) -> dict:
    base = f"{os.environ['OUMI_API_URL']}/projects/{os.environ['OUMI_PROJECT_ID']}"
    response = session.get(f"{base}{path}", params=params, timeout=60)
    response.raise_for_status()
    return response.json()


def main(operation_id: str, output_dir: str) -> None:
    session = requests.Session()
    session.headers["X-API-Key"] = os.environ["OUMI_API_KEY"]
    operation = get(session, f"/operations/{operation_id}")
    if operation["status"] != "completed":
        raise SystemExit(f"operation {operation_id} is {operation['status']}, not completed")
    evaluation_id = operation["result"]["evaluation_id"]

    items, token = [], None
    while True:
        page = get(
            session,
            f"/evaluations/{evaluation_id}/dataitems",
            pageSize=PAGE_SIZE,
            **({"pageToken": token} if token else {}),
        )
        items.extend(page.get("dataitems") or page.get("dataItems") or [])
        token = page.get("nextPageToken")
        if not token:
            break

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    (output_path / "oumi_dataitems.json").write_text(json.dumps({"dataitems": items}))
    with (output_path / "conversations.jsonl").open("w") as conversations_file:
        for item in items:
            conversation = item["conversation"]
            metadata = dict(conversation.get("metadata") or {})
            metadata["oumi_dataitem_id"] = item["id"]
            metadata["judge"] = {
                result["evaluatorDisplayName"]: result["judgment"]
                for result in item["evaluatorResults"]
            }
            row = {"messages": conversation["messages"], "metadata": metadata}
            conversations_file.write(json.dumps(row) + "\n")
    cost = operation.get("costCents")
    print(
        f"evaluation {evaluation_id}: {len(items)} conversations written to {output_path}"
        + (f" (cost ${cost / 100:.2f})" if cost is not None else "")
    )


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
