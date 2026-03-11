"""
main.py
CLI entry point for the CI/CD Pipeline Error Analysis AI Agent.

Usage examples:
    # Analyse a GitHub Actions run (fetches log automatically)
    python main.py analyze --repo owner/repo --run-id 1234567890 --platform github-actions

    # Analyse a local log file
    python main.py analyze --repo owner/repo --log-file build.log --platform jenkins

    # Analyse piped log input
    cat build.log | python main.py analyze --repo owner/repo --platform generic

    # Show the last agent report
    python main.py report
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich import box

load_dotenv()

console = Console()

# ── Logging setup ────────────────────────────────────────────────────────────

def setup_logging(level: str = "INFO") -> None:
    """Configure root logger with coloured console output."""
    import colorlog
    handler = colorlog.StreamHandler()
    handler.setFormatter(colorlog.ColoredFormatter(
        "%(log_color)s%(levelname)-8s%(reset)s %(cyan)s%(name)s%(reset)s: %(message)s",
        log_colors={
            "DEBUG": "white",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "bold_red",
        },
    ))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))


# ── CLI ──────────────────────────────────────────────────────────────────────

@click.group()
@click.option("--log-level", default=None, help="Logging level (DEBUG|INFO|WARNING|ERROR)")
def cli(log_level: str) -> None:
    """🤖 CI/CD Pipeline Error Analysis AI Agent."""
    level = log_level or os.getenv("LOG_LEVEL", "INFO")
    setup_logging(level)


def _dry_run_analyze(
    repo: str,
    platform: str,
    raw_log: str,
    run_id: str,
    pipeline_id: str,
):
    """
    Run log parsing + LLM analysis only — no GitHub API calls.
    Used for testing or when only a solution guide is needed.
    """
    from agent.state import AgentState
    from agent.tools.log_analyzer import analyze_log
    from agent.tools.solution_writer import generate_solution_guide

    state = AgentState(
        repo_name=repo,
        platform=platform,
        raw_log=raw_log,
        run_id=run_id,
        pipeline_id=pipeline_id,
    )
    state.log("Dry-run mode — GitHub API calls skipped")
    state = analyze_log(state)
    state = generate_solution_guide(state)
    return state


@cli.command()
@click.option("--repo", required=True, help='GitHub repo in "owner/repo" format.')
@click.option(
    "--platform",
    default="generic",
    type=click.Choice(["github-actions", "jenkins", "gitlab", "generic"], case_sensitive=False),
    show_default=True,
    help="CI/CD platform of the log.",
)
@click.option("--run-id", default=None, help="GitHub Actions workflow run ID.")
@click.option("--pipeline-id", default=None, help="GitLab CI pipeline ID.")
@click.option("--pr-number", default=None, type=int, help="PR number — agent reads the diff and fixes code directly on the PR branch.")
@click.option(
    "--log-file",
    default=None,
    type=click.Path(exists=True, readable=True),
    help="Path to a local CI/CD log file.",
)
@click.option(
    "--base-branch",
    default=None,
    help="Base branch for PR creation (default from env DEFAULT_BASE_BRANCH or 'main').",
)
@click.option(
    "--output",
    "output_file",
    default=None,
    type=click.Path(),
    help="Save the agent state JSON to a file.",
)
@click.option("--no-pr", is_flag=True, default=False, help="Analyse only — do not create PR.")
@click.option("--dry-run", is_flag=True, default=False, help="Parse & analyse log only; skip all GitHub API calls.")
def analyze(
    repo: str,
    platform: str,
    run_id: str,
    pipeline_id: str,
    pr_number: int,
    log_file: str,
    base_branch: str,
    output_file: str,
    no_pr: bool,
    dry_run: bool,
) -> None:
    """
    Analyse a CI/CD pipeline failure and attempt automatic remediation.

    The agent will:
    \b
    1. Parse the CI/CD log
    2. Perform LLM root-cause analysis
    3. Generate and apply code patches
    4. Raise a Pull Request (unless --no-pr is set)
    5. Fall back to a solution guide if auto-fix fails
    """
    from agent.core import CICDAgent
    from agent.github_client import GitHubClient

    # ── Resolve log input ─────────────────────────────────────────────────
    raw_log: str = ""

    if log_file:
        raw_log = Path(log_file).read_text(encoding="utf-8", errors="replace")
        console.print(f"[dim]Loaded log from {log_file} ({len(raw_log):,} chars)[/dim]")

    elif not sys.stdin.isatty():
        raw_log = sys.stdin.read()
        console.print(f"[dim]Loaded log from stdin ({len(raw_log):,} chars)[/dim]")

    elif platform == "github-actions" and run_id:
        # Will be fetched inside agent.run_from_github_actions
        raw_log = "__FETCH__"
    else:
        console.print(
            "[red]ERROR:[/red] Provide --log-file, pipe a log via stdin, "
            "or supply --run-id for GitHub Actions.",
        )
        sys.exit(1)

    # ── Run agent ─────────────────────────────────────────────────────────
    console.rule("[bold blue]🤖 CI/CD Pipeline Error Analysis Agent[/bold blue]")
    console.print(f"  Repo     : [green]{repo}[/green]")
    console.print(f"  Platform : [yellow]{platform}[/yellow]")
    if run_id:
        console.print(f"  Run ID   : {run_id}")
    if pr_number:
        console.print(f"  PR #     : [cyan]{pr_number}[/cyan] (will fix directly on PR branch)")
    if dry_run:
        console.print("  Mode     : [magenta]DRY RUN (no GitHub API calls)[/magenta]")

    try:
        if dry_run:
            state = _dry_run_analyze(repo, platform, raw_log, run_id, pipeline_id)
        else:
            agent = CICDAgent(base_branch=base_branch)

            if raw_log == "__FETCH__":
                state = agent.run_from_github_actions(
                    repo, int(run_id), pr_number=pr_number
                )
            else:
                state = agent.run(
                    repo_name=repo,
                    platform=platform,
                    raw_log=raw_log,
                    run_id=run_id,
                    pipeline_id=pipeline_id,
                    pr_number=pr_number,
                )
    except EnvironmentError as exc:
        console.print(f"\n[red]Configuration Error:[/red] {exc}")
        console.print("\nRun [bold]cp .env.example .env[/bold] and fill in your API keys.")
        sys.exit(1)
    except Exception as exc:
        console.print(f"\n[red]Agent Error:[/red] {exc}")
        logging.getLogger(__name__).exception("Unexpected agent error")
        sys.exit(1)

    # ── Display results ───────────────────────────────────────────────────
    _display_results(state, no_pr)

    # ── Save output ───────────────────────────────────────────────────────
    if output_file:
        Path(output_file).write_text(
            json.dumps(state.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )
        console.print(f"\n[dim]Agent state saved → {output_file}[/dim]")


def _display_results(state, no_pr: bool) -> None:
    """Render the final agent results to the terminal."""
    console.rule()

    # ── Analysis summary ─────────────────────────────────────────────────
    table = Table(box=box.ROUNDED, show_header=False, padding=(0, 1))
    table.add_column("Key", style="bold cyan", no_wrap=True)
    table.add_column("Value")
    table.add_row("Platform", state.platform)
    table.add_row("Repository", state.repo_name)
    table.add_row("Errors found", str(len(state.errors)))
    table.add_row("Root cause", state.root_cause or "—")
    table.add_row(
        "Confidence",
        state.llm_analysis.get("confidence", "—"),
    )
    console.print(Panel(table, title="[bold]📊 Analysis Summary[/bold]", border_style="blue"))

    # ── Error list ────────────────────────────────────────────────────────
    if state.errors:
        err_table = Table(box=box.SIMPLE, padding=(0, 1))
        err_table.add_column("#", style="dim", width=3)
        err_table.add_column("Type", style="yellow")
        err_table.add_column("Message")
        err_table.add_column("File", style="green")
        for i, err in enumerate(state.errors, 1):
            loc = f"{err.file_path}:{err.line_number}" if err.file_path else "—"
            err_table.add_row(str(i), err.error_type, err.message[:80], loc)
        console.print(Panel(err_table, title="[bold]🐛 Detected Errors[/bold]", border_style="yellow"))

    # ── Fix / PR result ────────────────────────────────────────────────────
    if no_pr:
        console.print(Panel(
            "[dim]--no-pr flag set: PR creation skipped.[/dim]",
            title="ℹ️  PR Skipped",
            border_style="dim",
        ))
    elif state.pr_created:
        console.print(Panel(
            f"[bold green]✅ Pull Request created![/bold green]\n\n"
            f"  PR #[bold]{state.pr_number}[/bold]\n"
            f"  URL: [link={state.pr_url}]{state.pr_url}[/link]\n"
            f"  Branch: [cyan]{state.branch_name}[/cyan]",
            title="[bold]🔀 Pull Request[/bold]",
            border_style="green",
        ))
    elif state.fix_succeeded:
        console.print(Panel(
            f"[yellow]⚠️  Code was patched but PR creation failed.[/yellow]\n"
            f"Branch: [cyan]{state.branch_name}[/cyan]",
            title="[bold]⚠️  Partial Fix[/bold]",
            border_style="yellow",
        ))
    else:
        # Fallback solution guide
        if state.solution_guide:
            console.print(Panel(
                Markdown(state.solution_guide),
                title="[bold]📋 Remediation Guide[/bold]",
                border_style="magenta",
            ))
        else:
            console.print(Panel(
                "[red]Auto-fix failed and no solution guide was generated.[/red]\n"
                "Check the agent log below for details.",
                title="[bold]❌ Auto-Fix Failed[/bold]",
                border_style="red",
            ))

    # ── Audit log (collapsed) ─────────────────────────────────────────────
    if state.agent_log:
        console.print("\n[dim]── Agent Audit Log ──────────────────────────────────────[/dim]")
        for entry in state.agent_log:
            console.print(f"  [dim]{entry}[/dim]")


@cli.command()
@click.argument("state_file", type=click.Path(exists=True))
def report(state_file: str) -> None:
    """
    Pretty-print a saved agent state JSON file.

    \b
    Example:
        python main.py report agent_state.json
    """
    data = json.loads(Path(state_file).read_text())
    console.print_json(json.dumps(data, indent=2, default=str))


if __name__ == "__main__":
    cli()
