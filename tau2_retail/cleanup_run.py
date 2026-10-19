"""List runs, or delete one run's tool implementations after its evaluation ends.

run_evaluation.py creates 16 implementations per run and records them in
runs.json. Once the evaluation has finished they're no longer needed; the tools
themselves stay. A run whose evaluation is still going is left alone unless
--force is given.

Reads OUMI_API_KEY, OUMI_API_URL and OUMI_PROJECT_ID from the environment.

    ../.venv/bin/python cleanup_run.py                 # list runs
    ../.venv/bin/python cleanup_run.py <run_tag>       # delete that run's implementations
"""

import argparse
import json

from run_evaluation import IDS_PATH, delete_implementations, load_runs, save_runs
from setup_platform import OumiClient

FINISHED_STATUSES = {"completed", "failed", "cancelled", "stopped"}


def list_runs(runs: dict) -> None:
    if not runs:
        print("no runs recorded")
    for run_tag, run in runs.items():
        state = "implementations deleted" if run.get("implementations_deleted") else (
            f"{len(run['implementation_ids'])} implementations"
        )
        print(f"{run_tag}  {run['model_name']}  operation {run['operation_id']}  {state}")


def cleanup(run_tag: str, force: bool) -> None:
    runs = load_runs()
    run = runs.get(run_tag)
    if run is None:
        raise SystemExit(f"unknown run {run_tag!r}; known runs: {', '.join(runs) or 'none'}")
    if run.get("implementations_deleted"):
        print(f"run {run_tag}: implementations already deleted")
        return
    client = OumiClient()
    if run["operation_id"] is not None and not force:
        status = client.request("GET", f"/operations/{run['operation_id']}")["status"]
        if status not in FINISHED_STATUSES:
            raise SystemExit(
                f"operation {run['operation_id']} is {status}; wait for it to finish "
                "or pass --force"
            )
    tool_ids = json.loads(IDS_PATH.read_text())["tool_ids"]
    delete_implementations(client, tool_ids, run["implementation_ids"])
    run["implementations_deleted"] = True
    save_runs(runs)
    print(f"run {run_tag}: deleted {len(run['implementation_ids'])} implementations")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("run_tag", nargs="?", help="run to clean up; omit to list runs")
    parser.add_argument("--force", action="store_true", help="skip the finished-run check")
    args = parser.parse_args()
    if args.run_tag:
        cleanup(args.run_tag, args.force)
    else:
        list_runs(load_runs())
