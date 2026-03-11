"""
agent/tools/log_analyzer.py
Tool: Parses raw CI/CD logs and calls the LLM for root-cause analysis.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.state import AgentState

from agent.llm import get_llm, build_analyze_prompt, invoke_json_llm
from agent.parsers import get_parser

logger = logging.getLogger(__name__)


def analyze_log(state: "AgentState") -> "AgentState":
    """
    Step 1 — Parse the CI/CD log and perform LLM root-cause analysis.

    Populates:
        state.errors          — parsed ErrorBlock list
        state.error_summary   — human-readable error summary
        state.root_cause      — LLM-identified root cause
        state.fix_strategy    — LLM-suggested fix strategy
        state.affected_files  — list of file paths to examine
        state.llm_analysis    — full LLM response dict

    Args:
        state: Current AgentState (must have raw_log and platform set).

    Returns:
        Updated AgentState.
    """
    state.log("Starting log analysis")

    # 1. Platform-specific log parsing
    parser = get_parser(state.platform)
    state.errors = parser.parse(state.raw_log)
    state.log(f"Parsed {len(state.errors)} error block(s) from log")

    if not state.errors:
        state.log("No errors found during parsing — sending full log to LLM")

    # 2. Build a compact error summary for the LLM
    error_lines = []
    for i, err in enumerate(state.errors, 1):
        line = f"{i}. [{err.error_type}] {err.message}"
        if err.file_path:
            line += f" (file: {err.file_path}"
            if err.line_number:
                line += f":{err.line_number}"
            line += ")"
        error_lines.append(line)
        # Also include context snippet (truncated)
        if err.context:
            error_lines.append("   Context: " + err.context[:300].replace("\n", " ↵ "))

    state.error_summary = "\n".join(error_lines) if error_lines else "No structured errors found."

    # 3. Call LLM for deep analysis
    # Truncate very long logs to stay within token limits (~12 k chars ≈ 3 k tokens)
    log_for_llm = state.raw_log[:12000] if len(state.raw_log) > 12000 else state.raw_log
    if len(state.raw_log) > 12000:
        state.log(f"Log truncated from {len(state.raw_log)} to 12 000 chars for LLM")

    try:
        llm = get_llm(temperature=0.0)
    except Exception as exc:
        logger.error("LLM init failed: %s", exc)
        state.log(f"LLM init failed: {exc}")
        state.root_cause = "LLM analysis unavailable — see parsed errors"
        state.fix_strategy = "Manual review required"
        return state

    prompt = build_analyze_prompt()

    try:
        analysis = invoke_json_llm(
            llm,
            prompt,
            {
                "platform": state.platform,
                "repo": state.repo_name,
                "log": log_for_llm,
                # If a PR diff was loaded, inject it so the LLM knows
                # EXACTLY what the developer changed before CI failed
                "pr_diff_section": (
                    "=== PR DIFF (code the developer changed) ===\n"
                    + state.pr_diff[:6000]
                    + "\n============================================="
                ) if state.pr_diff else "",
            },
        )
        state.llm_analysis = analysis
        state.root_cause = analysis.get("root_cause", "Unknown")
        state.fix_strategy = analysis.get("fix_strategy", "")
        state.affected_files = analysis.get("affected_files", [])
        state.log(
            f"LLM analysis complete — root cause: {state.root_cause[:100]} "
            f"| confidence: {analysis.get('confidence', 'unknown')}"
        )
    except Exception as exc:
        logger.error("LLM analysis failed: %s", exc)
        state.log(f"LLM analysis failed: {exc}")
        state.root_cause = "LLM analysis unavailable — see parsed errors"
        state.fix_strategy = "Manual review required"

    return state
