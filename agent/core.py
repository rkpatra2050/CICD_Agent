"""
agent/core.py
Main orchestration loop for the CI/CD Pipeline Error Analysis Agent.

Enterprise flow (PR-aware):
  1. Fetch CI/CD log  →  2. Read PR diff (what the developer changed)
  3. LLM root-cause analysis  →  4. Generate targeted code patches
  5. Commit fixes to the SAME PR branch  →  CI re-runs automatically
  Fallback: post solution guide as a PR comment

Standalone flow (no PR):
  1-3 same  →  4. Create a new fix branch  →  5. Open PR with fix
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from agent.state import AgentState
from agent.github_client import GitHubClient
from agent.pr_diff_reader import PRDiffReader
from agent.tools.log_analyzer import analyze_log
from agent.tools.file_editor import fetch_affected_files, generate_patches, apply_patches
from agent.tools.git_operations import create_fix_branch
from agent.tools.pr_creator import create_pull_request
from agent.tools.solution_writer import generate_solution_guide

logger = logging.getLogger(__name__)

MAX_FIX_ATTEMPTS = int(os.getenv("MAX_FIX_ATTEMPTS", "3"))
DEFAULT_BASE_BRANCH = os.getenv("DEFAULT_BASE_BRANCH", "main")


class CICDAgent:
    """
    Orchestrates the full CI/CD error analysis and auto-remediation pipeline.

    Two usage modes:

    PR-AWARE MODE (enterprise / office repos):
        agent.run(..., pr_number=42)
        → Reads exactly what the developer changed in PR #42
        → Fixes those files and commits back to the PR branch
        → CI re-runs automatically on the same PR
        → Posts analysis + fix status as a PR comment

    STANDALONE MODE:
        agent.run(...)
        → Creates a new fix branch
        → Opens a new PR with the fix
    """

    def __init__(
        self,
        github_token: Optional[str] = None,
        base_branch: Optional[str] = None,
    ) -> None:
        self.gh = GitHubClient(token=github_token)
        self.diff_reader = PRDiffReader(self.gh)
        self.base_branch = base_branch or DEFAULT_BASE_BRANCH

    # ── Public API ───────────────────────────────────────────────────────────

    def run(
        self,
        repo_name: str,
        platform: str,
        raw_log: str,
        run_id: Optional[str] = None,
        pipeline_id: Optional[str] = None,
        pr_number: Optional[int] = None,
    ) -> AgentState:
        """
        Execute the full agent pipeline.

        Args:
            repo_name:    "owner/repo"
            platform:     "github-actions" | "jenkins" | "gitlab" | "generic"
            raw_log:      Raw CI/CD log text
            run_id:       GitHub Actions run ID (optional)
            pipeline_id:  GitLab pipeline ID (optional)
            pr_number:    PR number that triggered the CI failure (enables
                          PR-aware mode — reads diff + commits fix to PR branch)
        """
        state = AgentState(
            repo_name=repo_name,
            platform=platform,
            raw_log=raw_log,
            run_id=run_id,
            pipeline_id=pipeline_id,
        )
        state.log(
            f"Agent started | repo={repo_name} platform={platform} "
            f"pr={pr_number or 'none'} run={run_id or 'none'}"
        )

        # ── STEP 1: Read PR diff for extra context ───────────────────────────
        if pr_number:
            try:
                state = self.diff_reader.enrich_state_with_pr_diff(state, pr_number)
            except Exception as exc:
                state.log(f"WARNING: PR diff read failed: {exc}")

        # ── STEP 2: Parse log + LLM root-cause analysis ──────────────────────
        state = self._step_analyze(state)

        # ── STEP 3: Decide if auto-fix is feasible ───────────────────────────
        if state.llm_analysis.get("requires_human_review"):
            state.log("LLM flagged requires_human_review → generating solution guide")
            return generate_solution_guide(state)

        if not state.affected_files:
            state.log("No affected files identified → generating solution guide")
            return generate_solution_guide(state)

        # ── STEP 4: Auto-fix ─────────────────────────────────────────────────
        if pr_number:
            # PR-aware: push fix directly onto the developer's PR branch
            state = self._fix_onto_pr_branch(state, pr_number)
        else:
            # Standalone: create a new branch + open a new PR
            state = self._fix_new_branch(state)

        # ── STEP 5: Fallback ─────────────────────────────────────────────────
        if not state.fix_succeeded:
            state.log("Auto-fix failed → generating solution guide")
            state = generate_solution_guide(state)

        return state

    def run_from_github_actions(
        self,
        repo_name: str,
        run_id: int,
        pr_number: Optional[int] = None,
    ) -> AgentState:
        """
        Fetch the log from GitHub Actions and run the agent.

        Args:
            repo_name:  "owner/repo"
            run_id:     GitHub Actions workflow run ID
            pr_number:  Associated PR number (enables PR-aware mode)
        """
        logger.info("Fetching Actions log for run %s", run_id)
        raw_log = self.gh.get_actions_run_log(repo_name, run_id)
        return self.run(
            repo_name=repo_name,
            platform="github-actions",
            raw_log=raw_log,
            run_id=str(run_id),
            pr_number=pr_number,
        )

    # ── Private helpers ──────────────────────────────────────────────────────

    def _step_analyze(self, state: AgentState) -> AgentState:
        try:
            return analyze_log(state)
        except Exception as exc:
            logger.error("Analysis step failed: %s", exc)
            state.log(f"CRITICAL: Analysis failed: {exc}")
            state.root_cause = "Analysis failed — see agent log"
            state.fix_strategy = "Manual review required"
            return state

    def _fix_onto_pr_branch(
        self, state: AgentState, pr_number: int
    ) -> AgentState:
        """
        PR-AWARE fix: commit changes directly onto the developer's PR branch.

        After committing, GitHub re-triggers the CI on that branch automatically —
        so the developer sees the fix inline in their own PR.
        """
        try:
            repo = self.gh.get_repo(state.repo_name)
            pr = repo.get_pull(pr_number)
            pr_branch = pr.head.ref
            state.branch_name = pr_branch
            state.log(f"PR-aware mode: targeting branch '{pr_branch}'")
        except Exception as exc:
            state.log(f"Could not resolve PR branch: {exc} — falling back to new branch")
            return self._fix_new_branch(state)

        patches_result: Optional[dict] = None

        for attempt in range(1, MAX_FIX_ATTEMPTS + 1):
            state.log(f"Attempt {attempt}/{MAX_FIX_ATTEMPTS} — branch: {pr_branch}")

            file_contents = self._fetch_files(state, pr_branch)
            if not file_contents:
                continue

            patches_result = self._generate(state, file_contents)
            if not patches_result:
                continue

            success = self._apply(state, patches_result, branch=pr_branch, base=pr_branch)
            if success:
                state.fix_succeeded = True
                state.pr_created = True   # fix is on the existing PR
                state.pr_number = pr_number
                state.log(
                    f"✅ Fix committed to PR #{pr_number} branch '{pr_branch}' "
                    f"on attempt {attempt} — CI will re-run automatically"
                )
                break

        return state

    def _fix_new_branch(self, state: AgentState) -> AgentState:
        """Standalone fix: create a new fix branch and open a new PR."""
        try:
            branch = create_fix_branch(state, self.gh, base_branch=self.base_branch)
        except Exception as exc:
            state.log(f"CRITICAL: Branch creation failed: {exc}")
            return state

        patches_result: Optional[dict] = None

        for attempt in range(1, MAX_FIX_ATTEMPTS + 1):
            state.log(f"Attempt {attempt}/{MAX_FIX_ATTEMPTS}")

            file_contents = self._fetch_files(state, self.base_branch)
            if not file_contents:
                continue

            patches_result = self._generate(state, file_contents)
            if not patches_result:
                continue

            success = self._apply(state, patches_result, branch=branch, base=self.base_branch)
            if success:
                state.fix_succeeded = True
                state.log(f"Patches applied on attempt {attempt}")
                break

        if state.fix_succeeded and patches_result:
            try:
                state = create_pull_request(
                    state, self.gh, patches_result, base_branch=self.base_branch
                )
            except Exception as exc:
                state.log(f"ERROR: PR creation failed: {exc}")

        return state

    def _fetch_files(self, state: AgentState, branch: str):
        try:
            contents = fetch_affected_files(state, self.gh, base_branch=branch)
            if not contents:
                state.log("No files fetched")
            return contents
        except Exception as exc:
            state.log(f"File fetch failed: {exc}")
            return {}

    def _generate(self, state: AgentState, file_contents: dict):
        try:
            result = generate_patches(state, file_contents)
            if not result or not result.get("patches"):
                state.log("LLM produced no patches")
                return None
            return result
        except Exception as exc:
            state.log(f"Patch generation failed: {exc}")
            return None

    def _apply(
        self,
        state: AgentState,
        patches_result: dict,
        branch: str,
        base: str,
    ) -> bool:
        try:
            return apply_patches(
                state, self.gh, patches_result, branch=branch, base_branch=base
            )
        except Exception as exc:
            state.log(f"Patch application failed: {exc}")
            return False


logger = logging.getLogger(__name__)

MAX_FIX_ATTEMPTS = int(os.getenv("MAX_FIX_ATTEMPTS", "3"))
DEFAULT_BASE_BRANCH = os.getenv("DEFAULT_BASE_BRANCH", "main")


class CICDAgent:
    """
    Orchestrates the full CI/CD error analysis and auto-remediation pipeline.

    Usage::

        agent = CICDAgent()
        state = agent.run(
            repo_name="owner/repo",
            platform="github-actions",
            raw_log="...",
        )
        if state.pr_created:
            print(f"PR opened: {state.pr_url}")
        else:
            print(state.solution_guide)
    """

    def __init__(
        self,
        github_token: Optional[str] = None,
        base_branch: Optional[str] = None,
    ) -> None:
        """
        Initialise the agent.

        Args:
            github_token: GitHub PAT. Falls back to GITHUB_TOKEN env var.
            base_branch: Base branch for PR creation. Falls back to
                         DEFAULT_BASE_BRANCH env var (default: 'main').
        """
        self.gh = GitHubClient(token=github_token)
        self.diff_reader = PRDiffReader(self.gh)
        self.base_branch = base_branch or DEFAULT_BASE_BRANCH

    # ── Public API ──────────────────────────────────────────────────────────

    def run(
        self,
        repo_name: str,
        platform: str,
        raw_log: str,
        run_id: Optional[str] = None,
        pipeline_id: Optional[str] = None,
        pr_number: Optional[int] = None,
    ) -> AgentState:
        """
        Execute the full agent pipeline.

        Args:
            repo_name: GitHub repository in "owner/repo" format.
            platform: CI/CD platform ('github-actions', 'jenkins',
                      'gitlab', 'generic').
            raw_log: Raw CI/CD log text to analyse.
            run_id: GitHub Actions workflow run ID (optional).
            pipeline_id: GitLab pipeline ID (optional).
            pr_number: Pull Request number — when provided the agent
                       reads the PR diff to understand exactly what
                       code changed before the CI failure.

        Returns:
            Final AgentState containing results, PR info, or solution guide.
        """
        # ── Initialise state ────────────────────────────────────────────────
        state = AgentState(
            repo_name=repo_name,
            platform=platform,
            raw_log=raw_log,
            run_id=run_id,
            pipeline_id=pipeline_id,
        )
        state.log(f"Agent started — repo={repo_name}, platform={platform}")

        # ── STEP 1: Enrich log with PR diff (if PR number known) ────────────
        if pr_number:
            state.log(f"PR #{pr_number} detected — reading changed files for context")
            try:
                state = self.diff_reader.enrich_state_with_pr_diff(state, pr_number)
            except Exception as exc:
                state.log(f"WARNING: Could not read PR diff: {exc}")

        # ── STEP 2: Log parsing + LLM analysis ─────────────────────────────
        state = self._step_analyze(state)

        # ── STEP 3: Determine if auto-fix is feasible ───────────────────────
        requires_review = state.llm_analysis.get("requires_human_review", False)
        no_affected_files = not state.affected_files

        if requires_review or no_affected_files:
            reason = (
                "LLM flagged 'requires_human_review'" if requires_review
                else "No affected files identified by LLM"
            )
            state.log(f"Skipping auto-fix: {reason}")
            state = generate_solution_guide(state)
            return state

        # ── STEP 4: Auto-fix loop ────────────────────────────────────────────
        # If we know the PR branch, push fixes directly to it (no new branch)
        if pr_number:
            state = self._step_autofix_to_pr(state, pr_number)
        else:
            state = self._step_autofix(state)

        # ── STEP 5: Fallback if all attempts failed ──────────────────────────
        if not state.fix_succeeded:
            state.log("All auto-fix attempts failed — generating solution guide")
            state = generate_solution_guide(state)

        return state

    def run_from_github_actions(
        self,
        repo_name: str,
        run_id: int,
        pr_number: Optional[int] = None,
    ) -> AgentState:
        """
        Convenience method: fetch log from GitHub Actions and run the agent.

        Args:
            repo_name: "owner/repo".
            run_id: GitHub Actions workflow run ID.
            pr_number: Associated PR number (optional — enables PR diff context).

        Returns:
            Final AgentState.
        """
        logger.info("Fetching GitHub Actions log for run %s", run_id)
        raw_log = self.gh.get_actions_run_log(repo_name, run_id)
        return self.run(
            repo_name=repo_name,
            platform="github-actions",
            raw_log=raw_log,
            run_id=str(run_id),
            pr_number=pr_number,
        )

    # ── Private steps ────────────────────────────────────────────────────────

    def _step_analyze(self, state: AgentState) -> AgentState:
        """Run log parsing and LLM root-cause analysis."""
        try:
            state = analyze_log(state)
        except Exception as exc:
            logger.error("Analysis step failed: %s", exc)
            state.log(f"CRITICAL: Analysis failed: {exc}")
            state.root_cause = "Analysis failed — see agent log"
            state.fix_strategy = "Manual review required"
        return state

    def _step_autofix(self, state: AgentState) -> AgentState:
        """
        Attempt automated code fixes in a retry loop.

        Creates a feature branch, fetches affected files, generates LLM
        patches, applies them, and opens a PR. Retries up to MAX_FIX_ATTEMPTS
        times if any step fails.
        """
        # Create the fix branch (shared across all attempts)
        try:
            branch = create_fix_branch(state, self.gh, base_branch=self.base_branch)
        except Exception as exc:
            logger.error("Branch creation failed: %s", exc)
            state.log(f"CRITICAL: Branch creation failed: {exc}")
            return state

        patches_result: Optional[dict] = None

        for attempt in range(1, MAX_FIX_ATTEMPTS + 1):
            state.log(f"Auto-fix attempt {attempt}/{MAX_FIX_ATTEMPTS}")

            # Fetch current file contents (re-fetch each attempt for freshness)
            try:
                file_contents = fetch_affected_files(
                    state, self.gh, base_branch=self.base_branch
                )
            except Exception as exc:
                state.log(f"Attempt {attempt}: file fetch failed: {exc}")
                continue

            if not file_contents:
                state.log(f"Attempt {attempt}: no files fetched, skipping")
                continue

            # Generate patches via LLM
            try:
                patches_result = generate_patches(state, file_contents)
            except Exception as exc:
                state.log(f"Attempt {attempt}: patch generation failed: {exc}")
                continue

            if not patches_result or not patches_result.get("patches"):
                state.log(f"Attempt {attempt}: LLM produced no patches")
                continue

            # Apply patches
            try:
                success = apply_patches(
                    state,
                    self.gh,
                    patches_result,
                    branch=branch,
                    base_branch=self.base_branch,
                )
            except Exception as exc:
                state.log(f"Attempt {attempt}: patch application failed: {exc}")
                continue

            if success:
                state.fix_succeeded = True
                state.log(f"Patches applied successfully on attempt {attempt}")
                break
            else:
                state.log(f"Attempt {attempt}: patch application incomplete")

        # ── Create PR if fix succeeded ──────────────────────────────────────
        if state.fix_succeeded and patches_result:
            try:
                state = create_pull_request(
                    state, self.gh, patches_result, base_branch=self.base_branch
                )
            except Exception as exc:
                logger.error("PR creation failed: %s", exc)
                state.log(f"ERROR: PR creation failed: {exc}")

        return state

    def _step_autofix_to_pr(
        self,
        state: AgentState,
        pr_number: int,
    ) -> AgentState:
        """
        Push fixes DIRECTLY to the existing PR branch.

        This is the enterprise-grade flow:
        - Developer opens a PR with broken code
        - CI fails
        - Agent reads the PR diff, fixes THOSE files
        - Agent commits the fix directly to the PR branch
        - CI re-runs automatically — no new branch or PR needed

        Args:
            state: Current AgentState (affected_files already set from PR diff).
            pr_number: The PR whose branch to push fixes to.

        Returns:
            Updated AgentState.
        """
        # Get the PR's head branch to commit fixes directly to it
        try:
            repo = self.gh.get_repo(state.repo_name)
            pr = repo.get_pull(pr_number)
            pr_branch = pr.head.ref
            state.branch_name = pr_branch
            state.log(f"Targeting PR #{pr_number} branch: {pr_branch}")
        except Exception as exc:
            state.log(f"WARNING: Could not get PR branch: {exc} — falling back to new branch")
            return self._step_autofix(state)

        patches_result: Optional[dict] = None

        for attempt in range(1, MAX_FIX_ATTEMPTS + 1):
            state.log(f"PR auto-fix attempt {attempt}/{MAX_FIX_ATTEMPTS}")

            # Fetch files from the PR's branch (not base)
            try:
                file_contents = fetch_affected_files(
                    state, self.gh, base_branch=pr_branch
                )
            except Exception as exc:
                state.log(f"Attempt {attempt}: file fetch failed: {exc}")
                continue

            if not file_contents:
                state.log(f"Attempt {attempt}: no files fetched, skipping")
                continue

            try:
                patches_result = generate_patches(state, file_contents)
            except Exception as exc:
                state.log(f"Attempt {attempt}: patch generation failed: {exc}")
                continue

            if not patches_result or not patches_result.get("patches"):
                state.log(f"Attempt {attempt}: LLM produced no patches")
                continue

            try:
                success = apply_patches(
                    state,
                    self.gh,
                    patches_result,
                    branch=pr_branch,
                    base_branch=pr_branch,  # read + write on same branch
                )
            except Exception as exc:
                state.log(f"Attempt {attempt}: patch application failed: {exc}")
                continue

            if success:
                state.fix_succeeded = True
                state.pr_created = True   # fix is already on the PR branch
                state.log(
                    f"✅ Fix committed directly to PR #{pr_number} "
                    f"branch '{pr_branch}' on attempt {attempt}"
                )
                break
            else:
                state.log(f"Attempt {attempt}: patch application incomplete")

        return state
