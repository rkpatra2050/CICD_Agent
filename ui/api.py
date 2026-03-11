"""
ui/api.py
─────────
FastAPI backend for the CI/CD Error Analysis Agent Dashboard.

Endpoints:
  GET  /                        → serve dashboard HTML
  GET  /api/health              → health check
  POST /api/analyze             → run agent on a repo/log/PR
  GET  /api/runs                → list all past agent runs
  GET  /api/runs/{run_id}       → get a specific run's state
  DELETE /api/runs/{run_id}     → delete a run record
  POST /api/install             → install agent into a target repo (copy files)
  GET  /api/stats               → dashboard statistics
  GET  /api/stream/{job_id}     → SSE stream of live agent logs

Run:
  uvicorn ui.api:app --reload --port 8000
"""

from __future__ import annotations

import json
import os
import sys
import uuid
import asyncio
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── Add parent to path so we can import agent ────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))

app = FastAPI(
    title="CI/CD Error Analysis Agent",
    description="AI-powered CI/CD pipeline error analysis and auto-fix dashboard",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory store (use a DB in production) ─────────────────────────────────
RUNS: Dict[str, Dict[str, Any]] = {}          # job_id → run state
LIVE_LOGS: Dict[str, List[str]] = {}          # job_id → log lines (SSE)

# ── Request/Response models ───────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    repo: str                              # "owner/repo"
    platform: str = "github-actions"
    run_id: Optional[str] = None           # GHA run ID
    pr_number: Optional[int] = None        # PR number
    error_log: Optional[str] = None        # raw pasted log
    dry_run: bool = False                  # skip actual commits

class InstallRequest(BaseModel):
    target_path: str                       # local path to target repo

# ── Background agent runner ───────────────────────────────────────────────────

async def _run_agent_job(job_id: str, req: AnalyzeRequest) -> None:
    """Run the agent in the background and stream logs via SSE."""
    LIVE_LOGS[job_id] = []
    RUNS[job_id]["status"] = "running"
    RUNS[job_id]["started_at"] = datetime.now(timezone.utc).isoformat()

    def push_log(msg: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        LIVE_LOGS[job_id].append(line)
        RUNS[job_id].setdefault("live_logs", []).append(line)

    try:
        push_log(f"Agent started for {req.repo}")
        push_log(f"Platform: {req.platform} | PR: {req.pr_number or 'none'} | Run: {req.run_id or 'none'}")

        # ── Import agent lazily (needs env vars) ─────────────────────────
        from agent.core import CICDAgent
        from agent.github_client import GitHubClient

        agent = CICDAgent()
        push_log("Agent initialised ✓")

        # ── Fetch or use pasted log ───────────────────────────────────────
        if req.run_id and not req.error_log:
            push_log(f"Fetching log for run {req.run_id}...")
            raw_log = agent.gh.get_actions_run_log(req.repo, int(req.run_id))
            push_log(f"Log fetched ({len(raw_log):,} chars)")
        elif req.error_log:
            raw_log = req.error_log
            push_log(f"Using pasted log ({len(raw_log):,} chars)")
        else:
            raise ValueError("Provide either run_id or error_log")

        # ── Run agent ─────────────────────────────────────────────────────
        push_log("Starting analysis...")
        state = agent.run(
            repo_name=req.repo,
            platform=req.platform,
            raw_log=raw_log,
            run_id=req.run_id,
            pr_number=req.pr_number,
        )

        push_log(f"Root cause: {state.root_cause}")
        push_log(f"Errors found: {len(state.errors)}")
        push_log(f"Fix succeeded: {state.fix_succeeded}")

        if state.fix_succeeded:
            push_log(f"✅ Fix committed to branch: {state.branch_name}")
            if state.pr_url:
                push_log(f"✅ PR: {state.pr_url}")
        elif state.solution_guide:
            push_log("📋 Auto-fix not applied — solution guide generated")

        # ── Store result ──────────────────────────────────────────────────
        RUNS[job_id].update({
            "status":        "success" if state.fix_succeeded else "guide",
            "finished_at":   datetime.now(timezone.utc).isoformat(),
            "state":         state.to_dict(),
            "fix_succeeded": state.fix_succeeded,
            "root_cause":    state.root_cause,
            "errors_count":  len(state.errors),
            "pr_url":        state.pr_url,
            "branch_name":   state.branch_name,
        })

    except Exception as exc:
        push_log(f"❌ Agent error: {exc}")
        RUNS[job_id].update({
            "status":      "error",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "error":       str(exc),
        })
    finally:
        LIVE_LOGS[job_id].append("__DONE__")


# ── API Routes ────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "version": "1.0.0", "runs": len(RUNS)}


@app.post("/api/analyze")
async def analyze(req: AnalyzeRequest, background_tasks: BackgroundTasks):
    """Trigger agent analysis. Returns a job_id to poll."""
    job_id = str(uuid.uuid4())[:8]
    RUNS[job_id] = {
        "job_id":     job_id,
        "repo":       req.repo,
        "platform":   req.platform,
        "pr_number":  req.pr_number,
        "run_id":     req.run_id,
        "status":     "queued",
        "queued_at":  datetime.now(timezone.utc).isoformat(),
        "live_logs":  [],
    }
    background_tasks.add_task(_run_agent_job, job_id, req)
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/runs")
def list_runs():
    runs = sorted(RUNS.values(), key=lambda r: r.get("queued_at", ""), reverse=True)
    # Return summary (without full state blob)
    return [
        {k: v for k, v in r.items() if k != "state"}
        for r in runs
    ]


@app.get("/api/runs/{job_id}")
def get_run(job_id: str):
    if job_id not in RUNS:
        raise HTTPException(404, "Run not found")
    return RUNS[job_id]


@app.delete("/api/runs/{job_id}")
def delete_run(job_id: str):
    RUNS.pop(job_id, None)
    LIVE_LOGS.pop(job_id, None)
    return {"deleted": job_id}


@app.get("/api/stream/{job_id}")
async def stream_logs(job_id: str):
    """Server-Sent Events stream of live agent logs."""
    async def event_generator():
        sent = 0
        while True:
            logs = LIVE_LOGS.get(job_id, [])
            while sent < len(logs):
                line = logs[sent]
                if line == "__DONE__":
                    yield f"data: __DONE__\n\n"
                    return
                yield f"data: {line}\n\n"
                sent += 1
            await asyncio.sleep(0.3)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/stats")
def stats():
    total    = len(RUNS)
    fixed    = sum(1 for r in RUNS.values() if r.get("fix_succeeded"))
    guide    = sum(1 for r in RUNS.values() if r.get("status") == "guide")
    errors   = sum(1 for r in RUNS.values() if r.get("status") == "error")
    running  = sum(1 for r in RUNS.values() if r.get("status") == "running")
    rate     = round((fixed / total * 100) if total else 0, 1)
    return {
        "total": total, "fixed": fixed, "guide": guide,
        "errors": errors, "running": running, "fix_rate": rate,
    }


@app.post("/api/install")
def install_to_repo(req: InstallRequest):
    """Copy agent files into a local target repo directory."""
    target = Path(req.target_path)
    if not target.exists():
        raise HTTPException(400, f"Path does not exist: {target}")

    source = Path(__file__).parent.parent
    copied = []

    # workflow
    wf_dst = target / ".github" / "workflows"
    wf_dst.mkdir(parents=True, exist_ok=True)
    shutil.copy(source / ".github" / "workflows" / "cicd-agent.yml", wf_dst / "cicd-agent.yml")
    copied.append(".github/workflows/cicd-agent.yml")

    # agent package
    agent_dst = target / "agent"
    if agent_dst.exists():
        shutil.rmtree(agent_dst)
    shutil.copytree(source / "agent", agent_dst,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    copied.append("agent/")

    # main.py + requirements
    for f in ["main.py", "requirements.txt"]:
        shutil.copy(source / f, target / f)
        copied.append(f)

    return {"installed": True, "target": str(target), "files": copied}


# ── Serve dashboard HTML ──────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def dashboard():
    html_path = Path(__file__).parent / "dashboard.html"
    return HTMLResponse(html_path.read_text())
