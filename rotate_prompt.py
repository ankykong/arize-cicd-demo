#!/usr/bin/env python3
"""
Script to rotate through prompt variants for A/B testing.
Updates prompts/rag_prompt.py with the next variant in the cycle.

Usage:
    python rotate_prompt.py          # Rotate through good prompts (default)
    python rotate_prompt.py --bad    # Use the bad prompt (for testing CI/CD blocking)
"""

import os
import sys
import json
from pathlib import Path
from prompts.prompt_variants import GOOD_PROMPT_VARIANTS, BAD_PROMPT

STATE_FILE = Path(__file__).parent / ".prompt_state.json"
RAG_PROMPT_FILE = Path(__file__).parent / "prompts" / "rag_prompt.py"


def get_current_index() -> int:
    """Get the current prompt index from state file."""
    if STATE_FILE.exists():
        with open(STATE_FILE, "r") as f:
            state = json.load(f)
            return state.get("current_index", 0)
    return 0


def save_current_index(index: int):
    """Save the current prompt index to state file."""
    with open(STATE_FILE, "w") as f:
        json.dump({"current_index": index}, f)


def update_rag_prompt(prompt: str, variant_label: str):
    """Update the rag_prompt.py file with the new prompt."""
    content = f'''# {variant_label} - Auto-rotated prompt
RAG_PROMPT = """{prompt}"""
'''
    with open(RAG_PROMPT_FILE, "w") as f:
        f.write(content)


def rotate_good_prompt():
    """Rotate to the next good prompt variant."""
    current_index = get_current_index()
    next_index = (current_index + 1) % len(GOOD_PROMPT_VARIANTS)
    
    new_prompt = GOOD_PROMPT_VARIANTS[next_index]
    update_rag_prompt(new_prompt, f"Variant {next_index}")
    save_current_index(next_index)
    
    print(f"✅ Rotated prompt: Variant {current_index} → Variant {next_index}")
    print(f"   Total good variants: {len(GOOD_PROMPT_VARIANTS)}")
    print(f"   Next rotation will be: Variant {(next_index + 1) % len(GOOD_PROMPT_VARIANTS)}")
    
    return next_index


def use_bad_prompt():
    """Use the bad prompt (for testing CI/CD blocking)."""
    update_rag_prompt(BAD_PROMPT, "BAD PROMPT (testing CI/CD blocking)")
    
    print("⚠️  Using BAD PROMPT - this should trigger benchmark failure")
    print("   This prompt encourages hallucination to test the CI/CD blocking mechanism")
    
    return -1


if __name__ == "__main__":
    if "--bad" in sys.argv:
        use_bad_prompt()
    else:
        rotate_good_prompt()

