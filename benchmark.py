import pandas as pd
from phoenix.evals import llm_classify, OpenAIModel
from openai import OpenAI
from arize.experimental.datasets import ArizeDatasetsClient
from arize.experimental.datasets.experiments.evaluators.base import (
    EvaluationResult,
    Evaluator,
)
from openai.types.chat import ChatCompletionToolParam
import json
import os
from datetime import datetime
import sys

import dotenv
dotenv.load_dotenv()

arize_client = ArizeDatasetsClient(api_key=os.getenv("ARIZE_API_KEY"))

# Get the current dataset version
dataset = arize_client.get_dataset(
    space_id=os.getenv("ARIZE_SPACE_ID"), dataset_id=os.getenv("ARIZE_DATASET_ID")
)

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


def hallucination_eval(output, dataset_row, **kwargs) -> EvaluationResult:
    from prompts.hallucination_eval import HALLUCINATION_EVAL_TEMPLATE
    print("evaluating for hallucinations")
    
    # Handle case when output is None (task failed)
    if output is None:
        return EvaluationResult(
            score=0,
            label="error",
            explanation="Task failed to produce output"
        )
    
    # Parse input messages from JSON array
    input_messages_raw = dataset_row["attributes.llm.input_messages"]
    input_messages = json.loads(input_messages_raw) if isinstance(input_messages_raw, str) else input_messages_raw
    
    # Extract system and user messages
    system_content = ""
    user_content = ""
    for msg in input_messages:
        role = msg.get("message.role", "")
        content = msg.get("message.content", "")
        if role == "system":
            system_content = content
        elif role == "user":
            user_content = content
    
    df_in = pd.DataFrame({
        "system_message": system_content,
        "user_message": user_content,
        "output": str(output),
    }, index=[0])
    
    rails = ["factual", "hallucinated"]
    eval_df = llm_classify(
        dataframe=df_in,
        template=HALLUCINATION_EVAL_TEMPLATE,
        model=OpenAIModel(model="gpt-4o-mini", api_key=os.getenv("OPENAI_API_KEY")),
        rails=rails,
        provide_explanation=True,
    )

    label = eval_df["label"][0]
    score = 1 if label == "factual" else 0
    explanation = eval_df["explanation"][0]
    return EvaluationResult(score=score, label=label, explanation=explanation)


def evaluate_experiment_results(experiment_df: pd.DataFrame, threshold: float = 0.8):
    """
    Evaluate experiment results DataFrame and determine success.
    
    Args:
        experiment_df: DataFrame containing experiment results from run_experiment
        threshold: Minimum acceptable score for evaluators (default: 0.8)
    
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
    
    # Find columns that contain evaluation scores (typically named like 'eval.<evaluator_name>.score')
    score_columns = [col for col in experiment_df.columns if 'score' in col.lower()]
    
    if not score_columns:
        # Fallback: look for columns with 'eval' in the name
        score_columns = [col for col in experiment_df.columns if 'eval' in col.lower()]
    
    metrics = {}
    all_passed = True
    details_parts = []
    
    for col in score_columns:
        # Calculate mean score for this metric, ignoring NaN values
        mean_score = experiment_df[col].dropna().mean()
        if pd.notna(mean_score):
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
            "details": "No evaluation metrics found in experiment results"
        }
    
    details = f"Experiment Results (threshold: {threshold:.0%}):\n" + "\n".join(details_parts)
    
    return {
        "success": all_passed,
        "metrics": metrics,
        "details": details
    }


def determine_experiment_success(experiment_df: pd.DataFrame, experiment_id: str, threshold: float = 0.8):
    """
    Evaluate experiment results and exit with appropriate code for CI/CD.
    
    Exit codes:
        0 - All metrics passed the threshold (success)
        1 - One or more metrics failed the threshold (failure)
    
    Args:
        experiment_df: DataFrame containing experiment results
        experiment_id: The experiment ID (for logging)
        threshold: Minimum acceptable score for evaluators (default: 0.8)
    """
    print(f"\n{'='*60}")
    print("EVALUATING EXPERIMENT RESULTS FOR CI/CD")
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


# Run the experiment - returns (experiment_id, result_dataframe)
experiment_id, experiment_df = arize_client.run_experiment(
    space_id=os.getenv("ARIZE_SPACE_ID"),
    dataset_id=os.getenv("ARIZE_DATASET_ID"),
    task=run_task,
    evaluators=[hallucination_eval],
    experiment_name=f"Github Actions RAG Benchmark {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
)

determine_experiment_success(experiment_df, experiment_id)