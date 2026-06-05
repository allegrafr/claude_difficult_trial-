import argparse
import json
import os
import re
import time
from typing import Any, Dict, List, Optional

import pandas as pd


DEFAULT_MODEL_NAME = os.environ.get("MODEL_NAME", "claude-sonnet-4-6")
DEFAULT_MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "1200"))
DEFAULT_SAVE_EVERY = int(os.environ.get("SAVE_EVERY", "50"))
DEFAULT_SLEEP_SECONDS = float(os.environ.get("SLEEP_SECONDS", "0"))
MOCK_MODE = os.environ.get("MOCK_MODE", "0") == "1"

RESULTS_FILE = "claude_results.csv"
WRONG_ONLY_FILE = "claude_wrong_only.csv"
LETTERS = "ABCDEFGHIJ"

SYSTEM_PROMPT = """
You are completing a multiple-choice benchmark evaluation.
Return exactly one valid JSON object and nothing else.
Do not use markdown.
Do not include text before or after the JSON.
The JSON object must have exactly these keys:
{
  "predicted_answer": "A",
  "reasoning": "brief explanation"
}
The predicted_answer value must be exactly one capital letter from A through J.
""".strip()


def normalize_answer(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""

    text = str(value).strip().upper()
    match = re.search(r"\b([A-J])\b", text)
    if match:
        return match.group(1)

    if len(text) > 0 and text[0] in LETTERS:
        return text[0]

    return ""


def answer_from_index(value: Any) -> str:
    try:
        index = int(float(value))
    except Exception:
        return ""

    if 0 <= index < len(LETTERS):
        return LETTERS[index]

    return ""


def get_correct_answer(row: pd.Series) -> str:
    answer = normalize_answer(row.get("correct_answer", ""))

    if answer:
        return answer

    answer = normalize_answer(row.get("answer", ""))

    if answer:
        return answer

    return answer_from_index(row.get("answer_index", ""))


def strip_code_fences(text: str) -> str:
    return re.sub(r"```(?:json)?\s*|\s*```", " ", text).strip()


def find_json_objects(text: str) -> List[Dict[str, Any]]:
    objects: List[Dict[str, Any]] = []
    decoder = json.JSONDecoder()

    for candidate in (text, strip_code_fences(text)):
        for match in re.finditer(r"\{", candidate):
            start = match.start()
            try:
                obj, _ = decoder.raw_decode(candidate[start:])
            except json.JSONDecodeError:
                continue

            if isinstance(obj, dict):
                objects.append(obj)

        if objects:
            break

    return objects


def extract_answer_from_text(text: str) -> str:
    patterns = [
        r'"predicted_answer"\s*:\s*"?([A-J])"?',
        r"'predicted_answer'\s*:\s*'?([A-J])'?",
        r"predicted_answer\s*[:=]\s*([A-J])\b",
        r"correct answer is\s+([A-J])\b",
        r"final answer\s*(?:is|:)\s*([A-J])\b",
        r"answer\s*(?:is|:)\s*\(?([A-J])\)?",
        r"\bchoose\s+([A-J])\b",
        r"\bselect\s+([A-J])\b",
        r"\boption\s+([A-J])\b",
        r"\b([A-J])\s+is correct\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return normalize_answer(match.group(1))

    # Last resort: lone capital letter A-J on its own line or at end of text
    match = re.search(r"(?:^|[\s\(\[])([A-J])(?:[\s\)\].,]|$)", text, flags=re.IGNORECASE | re.MULTILINE)
    if match:
        return normalize_answer(match.group(1))

    return ""


def parse_claude_response(raw_response: str) -> Dict[str, str]:
    text = str(raw_response or "").strip()

    objects = find_json_objects(text)
    for obj in reversed(objects):
        predicted = normalize_answer(obj.get("predicted_answer", ""))
        reasoning = str(obj.get("reasoning", "")).strip()

        if predicted:
            return {
                "predicted_answer": predicted,
                "reasoning": reasoning,
                "parse_status": "json",
            }

    recovered = extract_answer_from_text(text)
    if recovered:
        return {
            "predicted_answer": recovered,
            "reasoning": text,
            "parse_status": "recovered_from_text",
        }

    return {
        "predicted_answer": "",
        "reasoning": text,
        "parse_status": "failed",
    }


def call_claude(client: Optional[Any], prompt: str, model_name: str, max_tokens: int) -> Dict[str, str]:
    if MOCK_MODE:
        return {
            "raw_response": '{"predicted_answer": "A", "reasoning": "Mock response for local script testing."}',
            "stop_reason": "mock",
        }

    if client is None:
        raise RuntimeError("Anthropic client was not initialized.")

    response = client.messages.create(
        model=model_name,
        max_tokens=max_tokens,
        temperature=0,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    raw_text = ""
    for block in response.content:
        if getattr(block, "type", None) == "text":
            raw_text += block.text

    return {
        "raw_response": raw_text,
        "stop_reason": str(getattr(response, "stop_reason", "")),
    }


def load_existing_results(path: str) -> pd.DataFrame:
    if os.path.exists(path):
        return pd.read_csv(path)

    return pd.DataFrame()


def save_outputs(results: List[Dict[str, Any]]) -> None:
    results_df = pd.DataFrame(results)
    results_df.to_csv(RESULTS_FILE, index=False)

    if results_df.empty:
        pd.DataFrame().to_csv(WRONG_ONLY_FILE, index=False)
        return

    wrong_df = results_df[
        results_df["predicted_answer"].fillna("") != results_df["correct_answer"].fillna("")
    ].copy()

    wrong_columns = [
        "question_id",
        "question",
        "options",
        "correct_answer",
        "predicted_answer",
        "category",
        "source",
    ]

    existing_columns = [column for column in wrong_columns if column in wrong_df.columns]
    wrong_df[existing_columns].to_csv(WRONG_ONLY_FILE, index=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run prepared Claude prompts from a CSV file.")
    parser.add_argument("input_csv", help="CSV file with a prompt column")
    parser.add_argument("--rows", type=int, default=None, help="Optional number of rows to process")
    parser.add_argument("--model", default=DEFAULT_MODEL_NAME, help="Claude model name")
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS, help="Max output tokens")
    parser.add_argument("--save-every", type=int, default=DEFAULT_SAVE_EVERY, help="Save after this many new rows")
    parser.add_argument("--clear", action="store_true", help="Clear existing results before running")
    args = parser.parse_args()

    if args.clear:
        for path in (RESULTS_FILE, WRONG_ONLY_FILE):
            if os.path.exists(path):
                os.remove(path)
                print(f"Cleared: {path}")

    df = pd.read_csv(args.input_csv)

    if "prompt" not in df.columns:
        raise ValueError("Input CSV must contain a prompt column.")

    if args.rows is not None:
        df = df.head(args.rows)

    existing_df = load_existing_results(RESULTS_FILE)
    existing_results = existing_df.to_dict("records") if not existing_df.empty else []
    completed_ids = set(str(row.get("question_id")) for row in existing_results)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    client: Optional[Any] = None

    if MOCK_MODE:
        print("MOCK_MODE is on. No Anthropic API calls will be made.")
    else:
        if not api_key:
            print(
                "\nError: ANTHROPIC_API_KEY is not set.\n"
                "  Set it before running:\n"
                "    Windows PowerShell:  $env:ANTHROPIC_API_KEY = 'sk-ant-...'\n"
                "    Windows CMD:         set ANTHROPIC_API_KEY=sk-ant-...\n"
                "    Linux/macOS:         export ANTHROPIC_API_KEY=sk-ant-...\n"
                "\n"
                "  Or run in mock mode (no API key needed):\n"
                "    $env:MOCK_MODE = '1'\n"
            )
            raise SystemExit(1)
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            print("\nError: the anthropic package is not installed.\n  Run: pip install -r requirements.txt\n")
            raise SystemExit(1) from exc

        client = Anthropic(api_key=api_key)

    results = existing_results
    newly_processed = 0

    print(f"Input rows selected: {len(df)}")
    print(f"Already completed: {len(completed_ids)}")
    print(f"Model: {args.model}")
    print(f"Max tokens: {args.max_tokens}")
    print(f"Save every: {args.save_every}")

    for index, row in df.iterrows():
        question_id = str(row.get("question_id", index))

        if question_id in completed_ids:
            continue

        print(f"Running row {index + 1}/{len(df)} | question_id={question_id}")

        raw_response = ""
        stop_reason = ""
        error = ""

        try:
            claude_output = call_claude(client, str(row["prompt"]), args.model, args.max_tokens)
            raw_response = claude_output["raw_response"]
            stop_reason = claude_output["stop_reason"]
            parsed = parse_claude_response(raw_response)
        except Exception as exc:
            parsed = {"predicted_answer": "", "reasoning": "", "parse_status": "error"}
            error = str(exc)

        correct_answer = get_correct_answer(row)

        results.append(
            {
                "question_id": question_id,
                "correct_answer": correct_answer,
                "predicted_answer": parsed["predicted_answer"],
                "reasoning": parsed["reasoning"],
                "parse_status": parsed["parse_status"],
                "stop_reason": stop_reason,
                "question": row.get("question", ""),
                "options": row.get("options", ""),
                "category": row.get("category", ""),
                "source": row.get("source", row.get("src", "")),
                "raw_response": raw_response,
                "error": error,
            }
        )

        completed_ids.add(question_id)
        newly_processed += 1

        if newly_processed % args.save_every == 0:
            save_outputs(results)
            print(f"Saved progress after {newly_processed} new rows.")

        if DEFAULT_SLEEP_SECONDS > 0:
            time.sleep(DEFAULT_SLEEP_SECONDS)

    save_outputs(results)
    print("Finished.")
    print(f"Saved full results to: {RESULTS_FILE}")
    print(f"Saved wrong-only results to: {WRONG_ONLY_FILE}")


if __name__ == "__main__":
    main()
