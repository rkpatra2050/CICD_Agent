#!/usr/bin/env python3
"""
install_agent.py
────────────────
One-command installer: copies the AI agent into ANY target repo so that
repo's CI failures are automatically analysed and fixed.

Usage
-----
    python install_agent.py --target ../snake-game
    python install_agent.py --target /path/to/any-repo --dry-run

What it copies
--------------
    TARGET_REPO/
    ├── agent/                        ← full agent Python package
    ├── main.py                       ← CLI entry point
    ├── requirements.txt              ← Python dependencies
    └── .github/
        └── workflows/
            └── cicd-agent.yml        ← the AI agent workflow
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

# ── Colours (no external deps needed here) ────────────────────────────────────
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg: str)   -> None: print(f"{GREEN}  ✅  {msg}{RESET}")
def warn(msg: str) -> None: print(f"{YELLOW}  ⚠️   {msg}{RESET}")
def err(msg: str)  -> None: print(f"{RED}  ❌  {msg}{RESET}")
def info(msg: str) -> None: print(f"{CYAN}  ℹ️   {msg}{RESET}")
def step(msg: str) -> None: print(f"\n{BOLD}{msg}{RESET}")


# ── Source = directory this script lives in ───────────────────────────────────
SOURCE_ROOT = Path(__file__).parent.resolve()

# Files / dirs to copy into the target repo
COPY_MAP = {
    SOURCE_ROOT / "agent":                                 "agent",
    SOURCE_ROOT / "main.py":                              "main.py",
    SOURCE_ROOT / "requirements.txt":                     "requirements.txt",
    SOURCE_ROOT / ".github" / "workflows" / "cicd-agent.yml":
        ".github/workflows/cicd-agent.yml",
}


def copy_item(src: Path, dst: Path, dry_run: bool) -> None:
    """Copy a file or directory tree, creating parent dirs as needed."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dry_run:
        info(f"[dry-run] would copy  {src.relative_to(SOURCE_ROOT)}  →  {dst}")
        return
    if src.is_dir():
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        shutil.copy2(src, dst)
    ok(f"Copied  {src.name}  →  {dst.relative_to(dst.anchor)}")


def print_next_steps(target: Path) -> None:
    print(f"""
{BOLD}{'─'*60}
 🎉  Agent installed in: {target}
{'─'*60}{RESET}

{BOLD}Next steps:{RESET}

  1. Add TWO secrets to your GitHub repo
     (Settings → Secrets and variables → Actions):

     {CYAN}OPENAI_API_KEY{RESET}   →  your OpenAI key  (sk-...)
     {CYAN}AGENT_GH_TOKEN{RESET}   →  GitHub PAT with scopes:
                           repo  +  workflow  +  read:org

     How to create a PAT:
     github.com → Settings → Developer settings
       → Personal access tokens → Tokens (classic)
       → Generate new token → tick: repo, workflow

  2. Commit and push:

     {CYAN}cd {target}
     git add agent/ main.py requirements.txt .github/workflows/cicd-agent.yml
     git commit -m "chore: add CI/CD error-analysis agent"
     git push{RESET}

  3. {BOLD}Done!{RESET} From now on, every CI failure in this repo will be
     automatically analysed and fixed by the agent. ✨

     Trigger modes:
       • Auto    — any workflow in this repo fails → agent runs
       • Comment — type  /analyze  on any PR
       • Manual  — Actions tab → "🤖 CI/CD Error Analysis Agent" → Run workflow
""")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install the CI/CD Error Analysis Agent into a target repo.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python install_agent.py --target ../snake-game
  python install_agent.py --target /workspace/backend-service --dry-run
        """,
    )
    parser.add_argument(
        "--target", "-t",
        required=True,
        help="Path to the target repo folder (e.g. ../snake-game)",
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Show what would be copied without actually doing it.",
    )
    args = parser.parse_args()

    target = Path(args.target).resolve()
    dry_run: bool = args.dry_run

    # ── Validate target ────────────────────────────────────────────────────
    print(f"\n{BOLD}🤖 CI/CD Agent Installer{RESET}")
    print(f"   Source : {SOURCE_ROOT}")
    print(f"   Target : {target}")
    if dry_run:
        warn("Dry-run mode — nothing will be written.")

    if not target.exists():
        err(f"Target directory does not exist: {target}")
        err("Create it first or clone the repo, then re-run.")
        sys.exit(1)

    if not (target / ".git").exists():
        warn("Target does not look like a git repo (no .git folder).")
        answer = input("   Continue anyway? [y/N]: ").strip().lower()
        if answer != "y":
            print("Aborted.")
            sys.exit(0)

    # ── Check source files exist ───────────────────────────────────────────
    step("Step 1 — Checking source files…")
    missing = [src for src in COPY_MAP if not src.exists()]
    if missing:
        for m in missing:
            err(f"Source not found: {m}")
        sys.exit(1)
    ok("All source files found.")

    # ── Copy files ─────────────────────────────────────────────────────────
    step("Step 2 — Copying agent files…")
    for src, rel_dst in COPY_MAP.items():
        dst = target / rel_dst
        copy_item(src, dst, dry_run)

    # ── Warn about existing requirements.txt ──────────────────────────────
    step("Step 3 — Checking for conflicts…")
    req_dst = target / "requirements.txt"
    if req_dst.exists() and not dry_run:
        warn(
            "requirements.txt already exists in target. "
            "The agent's dependencies have been merged/overwritten.\n"
            "   Check it and remove any conflicts before pushing."
        )
    else:
        ok("No conflicts detected.")

    # ── Done ───────────────────────────────────────────────────────────────
    if not dry_run:
        print_next_steps(target)
    else:
        print(f"\n{YELLOW}Dry-run complete — no files were written.{RESET}")
        print(f"Re-run without --dry-run to actually install.\n")


if __name__ == "__main__":
    main()
