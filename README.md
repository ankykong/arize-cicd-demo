# Arize CI/CD Demo: Automated Prompt Evaluation Pipeline

This project demonstrates how to build a CI/CD pipeline for LLM prompts using GitHub Actions and Arize AX. It automatically rotates through prompt variants, runs hallucination evaluations, and blocks bad prompts from being deployed.

## Demo Video

https://cap.so/s/jdn0v72t104gv1s

## How It Works

### Automated Prompt Rotation

The system automatically rotates through **5 good prompt variants** every ~90 minutes using a scheduled GitHub Action. Each variant has a different style (Solutions Architect, Technical Expert, Concise Assistant, Step-by-step Guide, Strict Factual).

```
Variant 0 → Variant 1 → Variant 2 → Variant 3 → Variant 4 → Variant 0 ...
```

For each rotation:
1. **Rotate**: The next prompt variant is written to `prompts/rag_prompt.py`
2. **Benchmark**: The prompt is evaluated against a test dataset using Arize's experiment framework
3. **Evaluate**: A hallucination evaluator checks if responses are factual vs hallucinated
4. **Gate**: If the evaluation passes (≥80% factual), the changes are pushed. If it fails, the push is blocked.

### Evaluation Pipeline

The benchmark (`benchmark.py`) runs an experiment that:
- Fetches test cases from an Arize dataset
- Runs each test case through the current prompt using GPT-4o-mini
- Evaluates each response for hallucinations using an LLM judge
- Calculates the mean score across all test cases
- Exits with code 0 (pass) or 1 (fail) based on threshold

All experiment results are automatically logged to **Arize AX** for observability.

## GitHub Actions Workflows

| Workflow | Trigger | Description |
|----------|---------|-------------|
| **Rotate Prompt** | Scheduled (every ~90 min) | Rotates to next good prompt, runs benchmark, pushes if passes |
| **Test Bad Prompt** | Manual button | Uses a bad prompt to demo CI/CD blocking |
| **Hallucination Check** | PR to prompts/ | Runs benchmark on PRs, blocks merge if fails |

## Manual Triggers

You can manually trigger workflows from the GitHub Actions tab:

1. Go to **Actions** in your repository
2. Select the workflow you want to run
3. Click **Run workflow**

### Testing the Blocking Mechanism

To demonstrate how bad prompts are blocked:

1. Go to **Actions** → **Test Bad Prompt (CI/CD Blocking Demo)**
2. Click **Run workflow**
3. Watch the workflow fail at the benchmark step
4. The push is blocked because the bad prompt encourages hallucination

## What Happens When a Prompt Fails

When the benchmark detects a prompt that produces too many hallucinations:

```
============================================================
EVALUATING EXPERIMENT RESULTS FOR CI/CD
Experiment ID: abc123
============================================================
Experiment Results (threshold: 80%):
  eval.hallucination_eval.score: 45.00% [FAIL]
============================================================
STATUS: FAILURE - One or more metrics below threshold
CI/CD: Blocking merge/push
```

The workflow exits with code 1, which:
- **For scheduled rotations**: Prevents the bad prompt from being pushed
- **For PRs**: Blocks the merge (if set as required status check)

## Logging in Arize AX

All experiments are logged to Arize AX, where you can:

- **View experiment runs**: See each prompt variant's performance over time
- **Compare variants**: Analyze which prompts produce fewer hallucinations
- **Debug failures**: Drill into individual test cases to see why a prompt failed
- **Track trends**: Monitor prompt quality across deployments

Each experiment is named with a timestamp: `Github Actions RAG Benchmark YYYY-MM-DD HH:MM:SS`

## Project Structure

```
├── .github/workflows/
│   ├── rotate-prompt.yml      # Scheduled rotation + benchmark
│   ├── trigger-rotate.yml     # Manual bad prompt test
│   └── main.yml               # PR hallucination check
├── prompts/
│   ├── prompt_variants.py     # Good prompts + bad prompt
│   ├── rag_prompt.py          # Current active prompt (auto-updated)
│   └── hallucination_eval.py  # Evaluator template
├── benchmark.py               # Experiment runner + CI/CD gate
├── rotate_prompt.py           # Prompt rotation script
└── .prompt_state.json         # Tracks current variant index
```

## Setup

### Prerequisites

- GitHub repository with Actions enabled
- Arize AX account with API access
- OpenAI API key

### Environment Secrets

Add these secrets to your GitHub repository (Settings → Secrets → Actions):

| Secret | Description |
|--------|-------------|
| `ARIZE_API_KEY` | Your Arize API key |
| `ARIZE_SPACE_ID` | Your Arize space ID |
| `ARIZE_DATASET_ID` | ID of the evaluation dataset |
| `OPENAI_API_KEY` | OpenAI API key for GPT-4o-mini |
| `PAT_TOKEN` | GitHub Personal Access Token (for pushing from Actions) |

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Create .env file with your credentials
cp .env.example .env

# Rotate to next prompt (good)
python rotate_prompt.py

# Use bad prompt (for testing)
python rotate_prompt.py --bad

# Run benchmark
python benchmark.py
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     GitHub Actions                          │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐       │
│  │  Scheduled  │   │   Manual    │   │     PR      │       │
│  │  (90 min)   │   │   Trigger   │   │   Trigger   │       │
│  └──────┬──────┘   └──────┬──────┘   └──────┬──────┘       │
│         │                 │                 │               │
│         ▼                 ▼                 ▼               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              rotate_prompt.py                        │   │
│  │         (select good or bad prompt)                  │   │
│  └──────────────────────┬──────────────────────────────┘   │
│                         │                                   │
│                         ▼                                   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                benchmark.py                          │   │
│  │  • Run experiment against test dataset               │   │
│  │  • Evaluate for hallucinations                       │   │
│  │  • Exit 0 (pass) or 1 (fail)                        │   │
│  └──────────────────────┬──────────────────────────────┘   │
│                         │                                   │
└─────────────────────────┼───────────────────────────────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │      Arize AX         │
              │  • Experiment logs    │
              │  • Evaluation scores  │
              │  • Trace analysis     │
              └───────────────────────┘
```
