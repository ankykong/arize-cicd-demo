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


experiment = arize_client.run_experiment(
    space_id=os.getenv("ARIZE_SPACE_ID"),
    dataset_id=os.getenv("ARIZE_DATASET_ID"),
    task=run_task,
    evaluators=[hallucination_eval],
    experiment_name=f"Local RAG Benchmark {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
)