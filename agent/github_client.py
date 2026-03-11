"""
agent/github_client.py
Thin, error-handled wrapper around PyGithub for all repository operations.
"""

from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional, Tuple

from github import Github, GithubException, Repository, ContentFile

logger = logging.getLogger(__name__)


class GitHubClient:
    """
    Wraps PyGithub to provide high-level repository operations needed by the
    CI/CD agent: reading files, creating branches, committing patches, fetching
    Actions logs, and opening Pull Requests.
    """

    def __init__(self, token: Optional[str] = None) -> None:
        """
        Initialise the GitHub client.

        Args:
            token: GitHub Personal Access Token. Falls back to GITHUB_TOKEN env var.
        """
        token = token or os.getenv("GITHUB_TOKEN")
        if not token:
            raise EnvironmentError(
                "GITHUB_TOKEN is not set. "
                "Copy .env.example to .env and add your token."
            )
        self._gh = Github(token)
        self._token = token

    # ── Repository helpers ──────────────────────────────────────────────────

    def get_repo(self, repo_name: str) -> Repository.Repository:
        """
        Return the PyGithub Repository object.

        Args:
            repo_name: Full name in "owner/repo" format.

        Returns:
            PyGithub Repository object.
        """
        try:
            return self._gh.get_repo(repo_name)
        except GithubException as exc:
            logger.error("Failed to access repo %s: %s", repo_name, exc)
            raise

    # ── File operations ─────────────────────────────────────────────────────

    def get_file_content(
        self,
        repo_name: str,
        file_path: str,
        ref: str = "main",
    ) -> Tuple[str, str]:
        """
        Fetch the decoded content and SHA of a file.

        Args:
            repo_name: "owner/repo".
            file_path: Path relative to repo root.
            ref: Branch/tag/commit ref.

        Returns:
            Tuple of (content_string, sha).
        """
        repo = self.get_repo(repo_name)
        try:
            file_obj: ContentFile.ContentFile = repo.get_contents(file_path, ref=ref)  # type: ignore[assignment]
            content = file_obj.decoded_content.decode("utf-8")
            return content, file_obj.sha
        except GithubException as exc:
            logger.error("Failed to read %s@%s: %s", file_path, ref, exc)
            raise

    def update_file(
        self,
        repo_name: str,
        file_path: str,
        new_content: str,
        sha: str,
        commit_message: str,
        branch: str,
    ) -> None:
        """
        Commit an updated file to a specific branch.

        Args:
            repo_name: "owner/repo".
            file_path: Path relative to repo root.
            new_content: Full new content of the file.
            sha: Current file SHA (required by GitHub API).
            commit_message: Commit message.
            branch: Branch to push to.
        """
        repo = self.get_repo(repo_name)
        try:
            repo.update_file(
                path=file_path,
                message=commit_message,
                content=new_content,
                sha=sha,
                branch=branch,
            )
            logger.info("Committed %s → %s", file_path, branch)
        except GithubException as exc:
            logger.error("Failed to update %s: %s", file_path, exc)
            raise

    # ── Branch operations ───────────────────────────────────────────────────

    def create_branch(
        self,
        repo_name: str,
        branch_name: str,
        base_branch: str = "main",
    ) -> None:
        """
        Create a new branch from base_branch.

        Args:
            repo_name: "owner/repo".
            branch_name: Name for the new branch.
            base_branch: Source branch (default "main").
        """
        repo = self.get_repo(repo_name)
        try:
            base_ref = repo.get_branch(base_branch)
            repo.create_git_ref(
                ref=f"refs/heads/{branch_name}",
                sha=base_ref.commit.sha,
            )
            logger.info("Created branch %s from %s", branch_name, base_branch)
        except GithubException as exc:
            logger.error("Failed to create branch %s: %s", branch_name, exc)
            raise

    def branch_exists(self, repo_name: str, branch_name: str) -> bool:
        """Return True if the branch already exists in the remote repo."""
        repo = self.get_repo(repo_name)
        try:
            repo.get_branch(branch_name)
            return True
        except GithubException:
            return False

    # ── Pull Request ────────────────────────────────────────────────────────

    def create_pull_request(
        self,
        repo_name: str,
        title: str,
        body: str,
        head: str,
        base: str = "main",
        labels: Optional[List[str]] = None,
    ) -> Tuple[int, str]:
        """
        Open a Pull Request.

        Args:
            repo_name: "owner/repo".
            title: PR title.
            body: PR description (Markdown).
            head: Feature branch name.
            base: Target branch (default "main").
            labels: Optional list of label names to apply.

        Returns:
            Tuple of (pr_number, pr_html_url).
        """
        repo = self.get_repo(repo_name)
        try:
            pr = repo.create_pull(
                title=title,
                body=body,
                head=head,
                base=base,
            )
            if labels:
                try:
                    pr.set_labels(*labels)
                except GithubException:
                    logger.warning("Could not apply labels to PR #%d", pr.number)
            logger.info("Created PR #%d: %s", pr.number, pr.html_url)
            return pr.number, pr.html_url
        except GithubException as exc:
            logger.error("Failed to create PR: %s", exc)
            raise

    # ── PR comments ────────────────────────────────────────────────────────

    def create_pr_comment(self, repo_name: str, pr_number: int, body: str) -> int:
        """
        Post a Markdown comment on a pull request.

        Args:
            repo_name: "owner/repo".
            pr_number: PR number.
            body: Markdown body text.

        Returns:
            GitHub comment ID.
        """
        repo = self.get_repo(repo_name)
        pr = repo.get_pull(pr_number)
        comment = pr.create_issue_comment(body)
        logger.info("Posted PR comment %d on PR #%d", comment.id, pr_number)
        return comment.id

    def update_pr_comment(self, repo_name: str, comment_id: int, body: str) -> None:
        """
        Update an existing issue/PR comment body.

        Args:
            repo_name: "owner/repo".
            comment_id: GitHub comment ID.
            body: New Markdown body text.
        """
        repo = self.get_repo(repo_name)
        comment = repo.get_issue_comment(comment_id)
        comment.edit(body)
        logger.info("Updated PR comment %d", comment_id)

    # ── GitHub Actions logs ─────────────────────────────────────────────────

    def get_actions_run_log(self, repo_name: str, run_id: int) -> str:
        """
        Download and return the raw log text for a GitHub Actions workflow run.

        Args:
            repo_name: "owner/repo".
            run_id: GitHub Actions workflow run ID.

        Returns:
            Log text as a string.
        """
        import io
        import zipfile
        import requests

        repo = self.get_repo(repo_name)
        try:
            run = repo.get_workflow_run(run_id)
            log_url = run.logs_url
        except GithubException as exc:
            logger.error("Failed to get run %s: %s", run_id, exc)
            raise

        headers = {"Authorization": f"token {self._token}"}
        response = requests.get(log_url, headers=headers, timeout=60)
        response.raise_for_status()

        # Logs are returned as a zip archive
        log_parts: List[str] = []
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            for name in zf.namelist():
                with zf.open(name) as f:
                    try:
                        log_parts.append(f"=== {name} ===\n" + f.read().decode("utf-8", errors="replace"))
                    except Exception:
                        pass

        return "\n\n".join(log_parts)

    # ── Repo file listing ───────────────────────────────────────────────────

    def list_files(
        self,
        repo_name: str,
        path: str = "",
        ref: str = "main",
    ) -> List[str]:
        """
        Recursively list all file paths in a repo directory.

        Args:
            repo_name: "owner/repo".
            path: Sub-directory path (empty = root).
            ref: Branch/tag/commit ref.

        Returns:
            List of file paths relative to repo root.
        """
        repo = self.get_repo(repo_name)
        results: List[str] = []
        try:
            contents = repo.get_contents(path, ref=ref)
            if not isinstance(contents, list):
                contents = [contents]
            while contents:
                item = contents.pop(0)
                if item.type == "dir":
                    sub = repo.get_contents(item.path, ref=ref)
                    if isinstance(sub, list):
                        contents.extend(sub)
                    else:
                        contents.append(sub)
                else:
                    results.append(item.path)
        except GithubException as exc:
            logger.warning("Could not list files at '%s': %s", path, exc)
        return results
