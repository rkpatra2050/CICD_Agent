"""
agent/pr_diff_reader.py
Reads the changed files and their diffs from a GitHub Pull Request.
This gives the agent context about EXACTLY what code was modified
before the CI pipeline failed — the key to precise auto-fixes.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from github import GithubException

if TYPE_CHECKING:
    from agent.state import AgentState

logger = logging.getLogger(__name__)


class PRDiffReader:
    """
    Reads a Pull Request's changed files so the agent knows exactly
    what code was modified by the developer before the CI failure.

    This is critical for office/enterprise repos where:
    - A developer makes changes to backend service code
    - CI pipeline fails
    - Agent reads the EXACT lines changed in the PR
    - Agent fixes those specific lines (not random guesses)
    """

    def __init__(self, github_client) -> None:
        """
        Args:
            github_client: Authenticated GitHubClient instance.
        """
        self._gh = github_client

    def get_pr_changed_files(
        self,
        repo_name: str,
        pr_number: int,
    ) -> List[Dict]:
        """
        Return list of files changed in a PR with their diffs.

        Args:
            repo_name: "owner/repo"
            pr_number: Pull Request number

        Returns:
            List of dicts with keys:
              - filename: str
              - status: added | modified | removed | renamed
              - additions: int
              - deletions: int
              - patch: str  (unified diff)
              - raw_url: str
        """
        repo = self._gh.get_repo(repo_name)
        try:
            pr = repo.get_pull(pr_number)
            files = pr.get_files()
            result = []
            for f in files:
                result.append({
                    "filename": f.filename,
                    "status": f.status,
                    "additions": f.additions,
                    "deletions": f.deletions,
                    "patch": getattr(f, "patch", "") or "",
                    "raw_url": f.raw_url,
                })
                logger.info(
                    "PR #%d changed file: %s (%s +%d -%d)",
                    pr_number, f.filename, f.status, f.additions, f.deletions,
                )
            return result
        except GithubException as exc:
            logger.error("Failed to read PR #%d files: %s", pr_number, exc)
            return []

    def get_pr_context(
        self,
        repo_name: str,
        pr_number: int,
    ) -> Dict:
        """
        Return full PR context: title, description, base branch, changed files.

        Args:
            repo_name: "owner/repo"
            pr_number: Pull Request number

        Returns:
            Dict with PR metadata and changed files list.
        """
        repo = self._gh.get_repo(repo_name)
        try:
            pr = repo.get_pull(pr_number)
            return {
                "number": pr.number,
                "title": pr.title,
                "body": pr.body or "",
                "base_branch": pr.base.ref,
                "head_branch": pr.head.ref,
                "author": pr.user.login,
                "changed_files": self.get_pr_changed_files(repo_name, pr_number),
                "additions": pr.additions,
                "deletions": pr.deletions,
            }
        except GithubException as exc:
            logger.error("Failed to read PR #%d: %s", pr_number, exc)
            return {}

    def build_diff_summary(self, changed_files: List[Dict]) -> str:
        """
        Build a compact summary of PR changes for the LLM prompt.

        Args:
            changed_files: Output of get_pr_changed_files()

        Returns:
            Formatted string summarising what was changed.
        """
        if not changed_files:
            return "No changed files found in PR."

        lines = ["=== PR CHANGED FILES ==="]
        for f in changed_files:
            lines.append(
                f"\n[{f['status'].upper()}] {f['filename']} "
                f"(+{f['additions']} -{f['deletions']})"
            )
            if f["patch"]:
                # Include up to 60 lines of the diff for context
                patch_lines = f["patch"].splitlines()[:60]
                lines.append("--- diff ---")
                lines.extend(patch_lines)
                if len(f["patch"].splitlines()) > 60:
                    lines.append(f"... [{len(f['patch'].splitlines()) - 60} more lines]")
        lines.append("\n=== END PR CHANGES ===")
        return "\n".join(lines)

    def enrich_state_with_pr_diff(
        self,
        state: "AgentState",
        pr_number: int,
    ) -> "AgentState":
        """
        Enrich AgentState with PR diff data before LLM analysis.

        Appends the PR diff to state.raw_log so the LLM gets full
        context: both the CI error log AND the exact code that was changed.

        Args:
            state: Current AgentState
            pr_number: PR number to read diff from

        Returns:
            Updated AgentState with PR diff appended to raw_log.
        """
        state.log(f"Reading PR #{pr_number} diff for context")
        pr_context = self.get_pr_context(state.repo_name, pr_number)

        if not pr_context:
            state.log(f"WARNING: Could not read PR #{pr_number} context")
            return state

        changed_files = pr_context.get("changed_files", [])

        # Set affected files from PR diff (more precise than LLM guessing)
        pr_affected = [
            f["filename"] for f in changed_files
            if f["status"] in ("modified", "added")
        ]
        if pr_affected:
            state.affected_files = pr_affected
            state.log(f"PR diff reveals {len(pr_affected)} changed file(s): {pr_affected}")

        # Append the diff to the log so LLM sees it
        diff_summary = self.build_diff_summary(changed_files)
        state.raw_log = (
            state.raw_log
            + f"\n\n{'='*60}\n"
            + f"PR #{pr_number} by @{pr_context.get('author', '?')}: "
            + f"{pr_context.get('title', '')}\n"
            + diff_summary
        )

        state.log(
            f"PR context: author=@{pr_context.get('author')}, "
            f"files={len(changed_files)}, "
            f"+{pr_context.get('additions')} -{pr_context.get('deletions')}"
        )
        return state
