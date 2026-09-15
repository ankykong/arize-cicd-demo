import base64
import json
import os
import subprocess
import sys
import time
from datetime import datetime

import pandas as pd
from openai import OpenAI
from arize.experimental.datasets import ArizeDatasetsClient

import dotenv
dotenv.load_dotenv()

SPACE_ID = os.getenv("ARIZE_SPACE_ID")
DATASET_ID = os.getenv("ARIZE_DATASET_ID")
# AX-hosted evaluation task ("CI RAG Benchmark Hallucination Eval") that runs the
# "CI RAG Hallucination" LLM-as-judge evaluator against experiment runs.
EVAL_TASK_ID = os.getenv("ARIZE_EVAL_TASK_ID", "T25saW5lVGFzazozMjMzODpsVmFt")

POLL_INTERVAL_SECONDS = int(os.getenv("ARIZE_EVAL_POLL_INTERVAL", "10"))
POLL_TIMEOUT_SECONDS = int(os.getenv("ARIZE_EVAL_POLL_TIMEOUT", "900"))

arize_client = ArizeDatasetsClient(api_key=os.getenv("ARIZE_API_KEY"))

# Get the current dataset version
dataset = arize_client.get_dataset(space_id=SPACE_ID, dataset_id=DATASET_ID)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def task(dataset_row) -> str:
    from prompts.rag_prompt import RAG_PROMPT
    print("running task")
    prompt_vars = json.loads(
        dataset_row["attributes.llm.prompt_template.variables"]
    )

    formatted_prompt = RAG_PROMPT.format(**prompt_vars)

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        messages=[
            {"role": "user", "content": formatted_prompt},
        ],
    )
    return response.choices[0].message.content


def run_task(dataset_row) -> str:
    return task(dataset_row)


def ax_json(*args: str):
    """Run an ax CLI command and parse its JSON stdout."""
    cmd = ["ax", *args, "-o", "json"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ax command failed ({' '.join(cmd)}):\n{result.stderr}\n{result.stdout}"
        )
    return json.loads(result.stdout)


def resolve_experiment_global_id(experiment_id: str, experiment_name: str) -> str:
    """The AX task API needs the base64 global experiment ID. run_experiment may
    return a raw ID, so fall back to looking the experiment up by name."""
    try:
        if base64.b64decode(experiment_id).decode().startswith("Experiment:"):
            return experiment_id
    except Exception:
        pass

    experiments = ax_json(
        "experiments", "list", "--dataset", DATASET_ID, "--space", SPACE_ID
    ).get("experiments", [])
    for exp in experiments:
        if exp.get("name") == experiment_name:
            return exp["id"]
    raise RuntimeError(
        f"Could not find experiment named {experiment_name!r} in dataset {DATASET_ID}"
    )


def trigger_ax_eval(experiment_global_id: str) -> str:
    """Kick off the AX-hosted evaluation task against the experiment."""
    print(f"\nTriggering AX evaluation task {EVAL_TASK_ID} "
          f"for experiment {experiment_global_id}")
    run = ax_json(
        "tasks", "trigger-run", EVAL_TASK_ID,
        "--experiment-ids", experiment_global_id,
    )
    run_id = run["id"]
    print(f"AX eval task run started: {run_id} (status: {run.get('status')})")
    return run_id


def wait_for_ax_eval(run_id: str) -> dict:
    """Poll the AX task run until it reaches a terminal state."""
    deadline = time.time() + POLL_TIMEOUT_SECONDS
    while True:
        run = ax_json("tasks", "get-run", run_id)
        status = (run.get("status") or "").upper()
        print(f"AX eval run {run_id}: {status}")

        if status == "COMPLETED":
            print(
                f"AX eval run finished: {run.get('num_successes', 0)} scored, "
                f"{run.get('num_errors', 0)} errors, "
                f"{run.get('num_skipped', 0)} skipped"
            )
            if run.get("num_successes", 0) == 0:
                raise RuntimeError(
                    "AX eval run completed but scored 0 runs - check the task's "
                    "column mappings and experiment ID"
                )
            return run
        if status in ("CANCELLED", "CANCELED", "FAILED", "ERROR"):
            raise RuntimeError(f"AX eval run ended in status {status}: {run}")

        if time.time() > deadline:
            raise RuntimeError(
                f"Timed out after {POLL_TIMEOUT_SECONDS}s waiting for AX eval "
                f"run {run_id} (last status: {status})"
            )
        time.sleep(POLL_INTERVAL_SECONDS)


def fetch_ax_eval_results(experiment_global_id: str) -> pd.DataFrame:
    """Export the experiment runs (now annotated with AX eval scores) as a DataFrame."""
    cmd = [
        "ax", "experiments", "export", experiment_global_id,
        "--dataset", DATASET_ID, "--space", SPACE_ID, "--stdout",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to export experiment results:\n{result.stderr}")
    runs = json.loads(result.stdout)

    rows = []
    for run in runs:
        row = {"id": run.get("id"), "output": run.get("output")}
        for key, value in (run.get("additional_properties") or {}).items():
            if key.startswith("eval."):
                row[key] = value
        rows.append(row)
    return pd.DataFrame(rows)


def evaluate_experiment_results(experiment_df: pd.DataFrame, threshold: float = 0.8):
    """
    Evaluate AX eval results DataFrame and determine success.

    Args:
        experiment_df: DataFrame of experiment runs with AX eval score columns
        threshold: Minimum acceptable mean score for evaluators (default: 0.8)

    Returns:
        dict with keys:
            - success: bool indicating if all metrics passed threshold
            - metrics: dict of metric_name -> mean_score
            - details: human-readable summary
    """
    if experiment_df is None or experiment_df.empty:
        return {
            "success": False,
            "metrics": {},
            "details": "Failed to retrieve experiment results or no results found"
        }

    score_columns = [
        col for col in experiment_df.columns
        if col.startswith("eval.") and col.endswith(".score")
    ]

    metrics = {}
    all_passed = True
    details_parts = []

    for col in score_columns:
        scores = pd.to_numeric(experiment_df[col], errors="coerce").dropna()
        if scores.empty:
            continue
        mean_score = scores.mean()
        metrics[col] = mean_score
        passed = mean_score >= threshold
        status = "PASS" if passed else "FAIL"
        details_parts.append(f"  {col}: {mean_score:.2%} [{status}]")
        if not passed:
            all_passed = False

    if not metrics:
        return {
            "success": False,
            "metrics": {},
            "details": "No AX evaluation metrics found in experiment results"
        }

    details = f"AX Evaluation Results (threshold: {threshold:.0%}):\n" + "\n".join(details_parts)

    return {
        "success": all_passed,
        "metrics": metrics,
        "details": details
    }


def determine_experiment_success(experiment_df: pd.DataFrame, experiment_id: str, threshold: float = 0.8):
    """
    Evaluate AX eval results and exit with appropriate code for CI/CD.

    Exit codes:
        0 - All metrics passed the threshold (success)
        1 - One or more metrics failed the threshold (failure)
    """
    print(f"\n{'='*60}")
    print("EVALUATING AX EVAL RESULTS FOR CI/CD")
    print(f"Experiment ID: {experiment_id}")
    print(f"{'='*60}")

    result = evaluate_experiment_results(experiment_df, threshold)

    print(result["details"])
    print(f"{'='*60}")

    if result["success"]:
        print("STATUS: SUCCESS - All metrics passed threshold")
        print("CI/CD: Allowing merge/push")
        sys.exit(0)
    else:
        print("STATUS: FAILURE - One or more metrics below threshold")
        print("CI/CD: Blocking merge/push")
        sys.exit(1)


def main():
    experiment_name = f"Github Actions RAG Benchmark {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    # Step 1: run the task over the dataset. Evals are NOT run locally - they run
    # server-side on AX via the evaluation task below.
    experiment_id, _ = arize_client.run_experiment(
        space_id=SPACE_ID,
        dataset_id=DATASET_ID,
        task=run_task,
        experiment_name=experiment_name,
    )
    print(f"\nExperiment created: {experiment_id} ({experiment_name})")

    # Step 2: run the hallucination eval through AX against the new experiment.
    experiment_global_id = resolve_experiment_global_id(experiment_id, experiment_name)
    run_id = trigger_ax_eval(experiment_global_id)

    # Step 3: wait (poll + sleep) for the AX eval results to come in.
    wait_for_ax_eval(run_id)

    # Step 4: pull the AX eval scores and gate the benchmark on them.
    results_df = fetch_ax_eval_results(experiment_global_id)
    determine_experiment_success(results_df, experiment_global_id)


if __name__ == "__main__":
    main()
