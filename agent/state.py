"""
agent/state.py
Shared agent state — passed between every tool and orchestration step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ErrorBlock:
    """Represents a single parsed error extracted from a CI/CD log."""

    error_type: str
    message: str
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    context: str = ""
    raw_snippet: str = ""


@dataclass
class FixAttempt:
    """Records one attempt to fix an error."""

    attempt_number: int
    strategy: str
    files_changed: List[str] = field(default_factory=list)
    diff: str = ""
    success: bool = False
    error: Optional[str] = None


@dataclass
class AgentState:
    """Central state object shared across all agent tools and steps."""

    # ── Input ──────────────────────────────────────────────────────
    repo_name: str = ""           # "owner/repo"
    platform: str = ""            # github-actions | jenkins | gitlab | generic
    raw_log: str = ""             # Full raw CI/CD log text
    run_id: Optional[str] = None  # GitHub Actions run ID
    pipeline_id: Optional[str] = None  # GitLab pipeline ID

    # ── Parsed ─────────────────────────────────────────────────────
    errors: List[ErrorBlock] = field(default_factory=list)
    error_summary: str = ""

    # ── Analysis ───────────────────────────────────────────────────
    root_cause: str = ""
    fix_strategy: str = ""
    affected_files: List[str] = field(default_factory=list)
    llm_analysis: Dict[str, Any] = field(default_factory=dict)

    # ── Remediation ────────────────────────────────────────────────
    fix_attempts: List[FixAttempt] = field(default_factory=list)
    final_diff: str = ""
    fix_succeeded: bool = False

    # ── PR ─────────────────────────────────────────────────────────
    branch_name: str = ""
    pr_url: str = ""
    pr_number: Optional[int] = None
    pr_created: bool = False

    # ── PR Diff Context (from the developer's PR) ──────────────────
    pr_diff: str = ""                              # compact diff text for LLM
    pr_changed_files: List[str] = field(default_factory=list)  # files developer touched

    # ── Fallback ───────────────────────────────────────────────────
    solution_guide: str = ""

    # ── Meta ───────────────────────────────────────────────────────
    agent_log: List[str] = field(default_factory=list)

    def log(self, message: str) -> None:
        """Append a timestamped message to the agent audit log."""
        import datetime
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        entry = f"[{ts}] {message}"
        self.agent_log.append(entry)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize state to a plain dictionary."""
        import dataclasses
        return dataclasses.asdict(self)
