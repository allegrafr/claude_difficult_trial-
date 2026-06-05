# Claude Difficult MMLU-Pro Subset

This repository contains a prepared subset of difficult MMLU-Pro questions for Claude evaluation.

The subset contains **5,789 questions** that were answered incorrectly by both Qwen and Llama. Each row in `claude_ready_prompts.csv` already includes a fully formatted prompt, so no MMLU-Pro download, filtering, or prompt construction is needed before calling Claude.

## Files

- `claude_ready_prompts.csv`  
  Prepared input file. The `prompt` column is the exact text to send to Claude.

- `run_claude_prompts.py`  
  Python script that reads the CSV, calls Claude, and saves the results.

- `requirements.txt`  
  Python packages needed to run the script.

## Default settings

```text
MODEL_NAME = claude-sonnet-4-6
temperature = 0
max_tokens = 1200
save every 50 newly processed questions
```

The script saves progress every 50 newly processed questions and once more at the end. If restarted, it skips question IDs already present in `claude_results.csv`.

## Setup and run

Clone the repository:

```bash
git clone https://github.com/allegrafr/claude_difficult.git
cd claude_difficult
```

Install the required packages:

```bash
pip install -r requirements.txt
```

Set `ANTHROPIC_API_KEY` in your environment:

```powershell
# Windows PowerShell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
```

```bash
# Linux/macOS
export ANTHROPIC_API_KEY=sk-ant-...
```

Run a 50-question test first:

```bash
python run_claude_prompts.py claude_ready_prompts.csv --rows 50
```

If the test output looks correct, clear the test output files and run the full subset:

```bash
python run_claude_prompts.py claude_ready_prompts.csv --clear
```

## Output files

The script creates:

- `claude_results.csv`  
  Full results with `question_id`, `correct_answer`, `predicted_answer`, `reasoning`, `parse_status`, `stop_reason`, `question`, `options`, `category`, `source`, `raw_response`, and `error`.

- `claude_wrong_only.csv`  
  Only the questions Claude answered incorrectly, with `question_id`, `question`, `options`, `correct_answer`, `predicted_answer`, `category`, and `source`.

Please send both output files back after the run finishes.

## Optional settings

The defaults can be changed with command-line arguments or environment variables.

Examples:

```bash
python run_claude_prompts.py claude_ready_prompts.csv --rows 50 --max-tokens 1500 --save-every 10
```

```bash
MODEL_NAME="claude-sonnet-4-6" python run_claude_prompts.py claude_ready_prompts.csv --rows 50
```

Available environment variables:

```text
MODEL_NAME
MAX_TOKENS
SAVE_EVERY
SLEEP_SECONDS
```

## Local mock test without an API key

This only tests the script flow and output files. It does not call Claude and does not require an API key.

```bash
MOCK_MODE=1 python run_claude_prompts.py claude_ready_prompts.csv --rows 10
```
