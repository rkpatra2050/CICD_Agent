"""
agent/tools/git_operations.py
Tool: Branch creation and validation for the automated fix workflow.
"""

from __future__ import annotations

import datetime
import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.state import AgentState

from agent.github_client import GitHubClient

logger = logging.getLogger(__name__)

# Branch name prefix for auto-fix branches
BRANCH_PREFIX = "cicd-autofix"


def sanitize_branch_name(text: str) -> str:
    """
    Convert arbitrary text into a valid git branch name component.

    Args:
        text: Raw text (e.g., error type or root cause excerpt).

    Returns:
        Sanitized, lowercase, hyphen-separated string.
    """
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text[:40]  # keep it short


def create_fix_branch(
    state: "AgentState",
    gh: GitHubClient,
    base_branch: str = "main",
) -> str:
    """
    Create a new feature branch for the auto-fix changes.

    The branch name is derived from the root cause and a timestamp to
    ensure uniqueness: e.g., ``cicd-autofix/import-error-20260310T143000``.

    Args:
        state: Current AgentState (root_cause must be set).
        gh: Authenticated GitHubClient.
        base_branch: Branch to fork from.

    Returns:
        The created branch name.

    Raises:
        Exception: If branch creation fails.
    """
    ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    cause_slug = sanitize_branch_name(state.root_cause[:40]) if state.root_cause else "error"
    branch_name = f"{BRANCH_PREFIX}/{cause_slug}-{ts}"

    state.log(f"Creating branch: {branch_name} from {base_branch}")

    if gh.branch_exists(state.repo_name, branch_name):
        state.log(f"Branch {branch_name} already exists, using it")
    else:
        gh.create_branch(
            repo_name=state.repo_name,
            branch_name=branch_name,
            base_branch=base_branch,
        )
        state.log(f"Branch created: {branch_name}")

    state.branch_name = branch_name
    return branch_name
