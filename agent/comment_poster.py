"""
agent/comment_poster.py
───────────────────────
Standalone module for posting and updating rich PR comments from Python.

Used when the agent runs locally (not via GitHub Actions JS steps) and needs
to post the analysis result back to the PR that triggered the CI failure.

Usage
-----
    from agent.comment_poster import PRCommentPoster
    from agent.state import AgentState

    poster = PRCommentPoster(gh_client)
    comment_id = poster.post_placeholder(pr_number)   # ← post immediately
    # … run agent …
    poster.update_with_result(comment_id, state, pr_number)  # ← update
"""

from __future__ import annotations

import logging
from typing import Optional

from agent.state import AgentState

log = logging.getLogger(__name__)


class PRCommentPoster:
    """Post and update structured PR comments via PyGithub."""

    def __init__(self, github_client, repo_name: str) -> None:
        """
        Parameters
        ----------
        github_client : agent.github_client.GitHubClient
            Already-authenticated client.
        repo_name : str
            "owner/repo" string for all API calls.
        """
        self._gh = github_client
        self._repo_name = repo_name

    # ──────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────

    def post_placeholder(self, pr_number: int, run_id: str = "", platform: str = "") -> Optional[int]:
        """
        Post an immediate "Analyzing…" comment on the PR so the developer
        gets instant feedback.  Returns the comment ID for later update.

        Parameters
        ----------
        pr_number : int
            Pull-request number.
        run_id : str
            Failed workflow run ID (for display only).
        platform : str
            CI platform name (for display only).

        Returns
        -------
        int | None
            GitHub comment ID, or None if posting failed.
        """
        body = "\n".join([
            "## 🤖 CI/CD Error Analysis Agent",
            "",
            "> **Status:** 🔄 Analyzing your pipeline failure…",
            "",
            "| Field | Value |",
            "|---|---|",
            f"| **Platform** | `{platform or 'detecting…'}` |",
            f"| **Run ID**   | `{run_id or 'detecting…'}` |",
            f"| **PR**       | #{pr_number} |",
            "",
            "_This comment will be updated with the full analysis and fix._",
        ])

        try:
            comment_id = self._gh.create_pr_comment(self._repo_name, pr_number, body)
            log.info("Posted placeholder comment %s on PR #%s", comment_id, pr_number)
            return comment_id
        except Exception as exc:
            log.warning("Could not post placeholder comment: %s", exc)
            return None

    def update_with_result(
        self,
        comment_id: Optional[int],
        state: AgentState,
        pr_number: int,
    ) -> None:
        """
        Update (or create) the PR comment with the full analysis result.

        Parameters
        ----------
        comment_id : int | None
            ID returned by :meth:`post_placeholder`.  If None a new comment
            is created instead of updating.
        state : AgentState
            Completed agent state after the run.
        pr_number : int
            Pull-request number.
        """
        body = self._build_result_comment(state, pr_number)
        try:
            if comment_id:
                self._gh.update_pr_comment(self._repo_name, comment_id, body)
                log.info("Updated comment %s on PR #%s", comment_id, pr_number)
            else:
                cid = self._gh.create_pr_comment(self._repo_name, pr_number, body)
                log.info("Created new result comment %s on PR #%s", cid, pr_number)
        except Exception as exc:
            log.error("Failed to update PR comment: %s", exc)

    def post_analysis_comment(self, state: AgentState, pr_number: int) -> Optional[int]:
        """
        Convenience: post the full result comment in one shot (no placeholder).

        Returns the new comment ID or None on failure.
        """
        body = self._build_result_comment(state, pr_number)
        try:
            comment_id = self._gh.create_pr_comment(self._repo_name, pr_number, body)
            log.info("Posted result comment %s on PR #%s", comment_id, pr_number)
            return comment_id
        except Exception as exc:
            log.error("Failed to post analysis comment: %s", exc)
            return None

    # ──────────────────────────────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────────────────────────────

    def _build_result_comment(self, state: AgentState, pr_number: int) -> str:
        """Return the full Markdown body for the analysis result comment."""

        # ── Detected errors list ──────────────────────────────────────────
        errors_md = "\n".join(
            f"{i+1}. **[{e.error_type}]** {e.message[:120]}"
            + (f" → `{e.file_path}{':'+str(e.line_number) if e.line_number else ''}`"
               if e.file_path else "")
            for i, e in enumerate(state.errors)
        ) or "_No structured errors extracted_"

        # ── PR changed files ──────────────────────────────────────────────
        changed_files_md = "\n".join(
            f"- `{f}`" for f in state.pr_changed_files
        ) or "_none_"

        # ── Patched files ─────────────────────────────────────────────────
        fixed_files_md = "_none_"
        if state.fix_attempts:
            last = state.fix_attempts[-1]
            files = last.get("files_changed", [])
            if files:
                fixed_files_md = "\n".join(f"- `{f}`" for f in files)

        # ── Audit log ─────────────────────────────────────────────────────
        audit_log_md = "\n".join(state.agent_log) or "_No log entries_"

        # ── Status / fix block ────────────────────────────────────────────
        if state.fix_succeeded:
            status_icon = "✅"
            status_line = "**Auto-fix committed to this PR branch — CI will re-run automatically.**"
            fix_block = "\n".join([
                "### ✅ What Was Fixed",
                "",
                f"**Branch:** `{state.branch_name}`",
                "",
                "**Files patched:**",
                fixed_files_md,
                "",
                "> ⚡ GitHub has already queued a new CI run on your PR.",
                '> Review the diff in the **"Files changed"** tab, then merge when green.',
            ])
        elif state.solution_guide:
            status_icon = "📋"
            status_line = "**Auto-fix was not safe — full solution guide below.**"
            fix_block = "\n".join([
                "### 📋 Step-by-Step Solution Guide",
                "",
                state.solution_guide,
            ])
        else:
            status_icon = "❌"
            status_line = "**Analysis failed — check your secrets or run the agent manually.**"
            fix_block = "_See audit log below for details._"

        confidence = ""
        if state.llm_analysis and isinstance(state.llm_analysis, dict):
            confidence = str(state.llm_analysis.get("confidence", "—"))
        else:
            confidence = "—"

        parts = [
            f"## 🤖 CI/CD Error Analysis Agent — {status_icon}",
            "",
            f"> {status_line}",
            "",
            "---",
            "",
            "### 🔍 Root Cause",
            "",
            f"> {state.root_cause or '_Analysis unavailable_'}",
            "",
            f"**Confidence:** {confidence}  ",
            f"**Platform:** `{state.platform}`",
            "",
            "### 🐛 Detected Errors",
            "",
            errors_md,
            "",
            "### 📁 Files You Changed (PR diff)",
            "",
            changed_files_md,
            "",
            "### 🛠️ Fix Strategy",
            "",
            state.fix_strategy or "_See solution guide below_",
            "",
            "---",
            "",
            fix_block,
            "",
            "---",
            "",
            "<details>",
            "<summary>🔎 Agent Audit Log (click to expand)</summary>",
            "",
            "```",
            audit_log_md,
            "```",
            "</details>",
            "",
            "---",
            f"_🤖 CI/CD Error Analysis Agent • PR #{pr_number}_",
        ]

        return "\n".join(parts)
