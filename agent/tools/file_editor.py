"""
agent/tools/file_editor.py
Tool: Reads repository files and applies LLM-generated patches.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from agent.state import AgentState

from agent.github_client import GitHubClient
from agent.llm import get_llm, build_fix_prompt, invoke_json_llm

logger = logging.getLogger(__name__)


# Maximum characters of file content sent to the LLM per file
_MAX_FILE_CHARS = 6000


def fetch_affected_files(
    state: "AgentState",
    gh: GitHubClient,
    base_branch: str = "main",
) -> Dict[str, str]:
    """
    Fetch the content of every file listed in state.affected_files.

    Args:
        state: Current AgentState.
        gh: Authenticated GitHubClient.
        base_branch: Branch to read files from.

    Returns:
        Dict mapping file_path → file_content.
    """
    file_contents: Dict[str, str] = {}
    for path in state.affected_files:
        try:
            content, _ = gh.get_file_content(state.repo_name, path, ref=base_branch)
            file_contents[path] = content
            state.log(f"Fetched file: {path} ({len(content)} chars)")
        except Exception as exc:
            logger.warning("Could not fetch %s: %s", path, exc)
            state.log(f"WARNING: Could not fetch {path}: {exc}")
    return file_contents


def generate_patches(
    state: "AgentState",
    file_contents: Dict[str, str],
) -> Optional[Dict]:
    """
    Ask the LLM to generate code patches for the identified errors.

    Args:
        state: Current AgentState (root_cause and fix_strategy must be set).
        file_contents: Dict of file_path → content.

    Returns:
        Parsed LLM response dict with 'patches', 'commit_message',
        'pr_title', 'pr_body', or None on failure.
    """
    if not file_contents:
        state.log("No file contents available — cannot generate patches")
        return None

    # Build the file-contents block for the prompt (truncated per file)
    fc_block = ""
    for path, content in file_contents.items():
        truncated = content[:_MAX_FILE_CHARS]
        fc_block += f"\n--- {path} ---\n{truncated}\n"
        if len(content) > _MAX_FILE_CHARS:
            fc_block += f"... [{len(content) - _MAX_FILE_CHARS} chars truncated] ...\n"

    llm = get_llm(temperature=0.1)
    prompt = build_fix_prompt()

    try:
        result = invoke_json_llm(
            llm,
            prompt,
            {
                "root_cause": state.root_cause,
                "fix_strategy": state.fix_strategy,
                "affected_files": ", ".join(state.affected_files),
                "file_contents": fc_block,
            },
        )
        state.log(f"LLM generated {len(result.get('patches', []))} patch(es)")
        return result
    except Exception as exc:
        logger.error("Patch generation failed: %s", exc)
        state.log(f"Patch generation failed: {exc}")
        return None


def apply_patches(
    state: "AgentState",
    gh: GitHubClient,
    patches_result: Dict,
    branch: str,
    base_branch: str = "main",
) -> bool:
    """
    Apply LLM-generated patches by committing each file change to the branch.

    Args:
        state: Current AgentState.
        gh: Authenticated GitHubClient.
        patches_result: Full LLM response dict from generate_patches().
        branch: Feature branch to commit changes to.
        base_branch: Base branch to read current file SHAs from.

    Returns:
        True if all patches were applied successfully, False otherwise.
    """
    patches: List[Dict] = patches_result.get("patches", [])
    commit_message: str = patches_result.get(
        "commit_message", "fix: auto-remediate CI/CD pipeline errors"
    )

    if not patches:
        state.log("No patches to apply")
        return False

    all_ok = True
    files_changed: List[str] = []

    for patch in patches:
        file_path: str = patch.get("file_path", "")
        original: str = patch.get("original_snippet", "")
        fixed: str = patch.get("fixed_snippet", "")
        explanation: str = patch.get("explanation", "")

        if not file_path or not original or not fixed:
            state.log(f"Skipping malformed patch for {file_path}")
            continue

        try:
            # Get current file content and SHA from base branch
            current_content, sha = gh.get_file_content(
                state.repo_name, file_path, ref=base_branch
            )

            if original not in current_content:
                state.log(
                    f"WARNING: snippet not found in {file_path} — "
                    "trying fuzzy match"
                )
                # Fuzzy fallback: try stripping leading whitespace
                stripped_original = "\n".join(l.strip() for l in original.splitlines())
                stripped_content = "\n".join(l.strip() for l in current_content.splitlines())
                if stripped_original not in stripped_content:
                    state.log(f"SKIP: Cannot locate patch target in {file_path}")
                    all_ok = False
                    continue

            new_content = current_content.replace(original, fixed, 1)

            gh.update_file(
                repo_name=state.repo_name,
                file_path=file_path,
                new_content=new_content,
                sha=sha,
                commit_message=f"{commit_message}\n\n{explanation}",
                branch=branch,
            )
            files_changed.append(file_path)
            state.log(f"Applied patch to {file_path}: {explanation[:80]}")

        except Exception as exc:
            logger.error("Failed to apply patch to %s: %s", file_path, exc)
            state.log(f"ERROR applying patch to {file_path}: {exc}")
            all_ok = False

    # Record the attempt
    from agent.state import FixAttempt
    attempt_num = len(state.fix_attempts) + 1
    state.fix_attempts.append(
        FixAttempt(
            attempt_number=attempt_num,
            strategy=state.fix_strategy,
            files_changed=files_changed,
            success=all_ok and bool(files_changed),
        )
    )

    if files_changed:
        state.final_diff = f"Files modified: {', '.join(files_changed)}"

    return all_ok and bool(files_changed)
