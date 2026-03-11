# 🚀 Deploying the CI/CD Agent to GitHub — Complete Setup Guide

This guide shows you exactly how to deploy the agent so it watches
**all your repos** and automatically fixes CI/CD failures.

---

## Architecture: How It Works in Your Office

```
Your Office Repos (backend-service, frontend-app, api-gateway...)
         │
         │  Developer makes a change → opens a PR
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│              GitHub Actions (your repo)                  │
│                                                         │
│  1. ci-pipeline.yml runs (build, test, lint...)         │
│              │                                          │
│              │  ❌ FAILS                                │
│              ▼                                          │
│  2. cicd-agent.yml TRIGGERS automatically               │
│              │                                          │
│              ├─ Downloads the failed run log            │
│              ├─ Reads the PR diff (what changed)        │
│              ├─ GPT-4 root-cause analysis               │
│              ├─ Generates code fix patches              │
│              ├─ Commits fix to PR branch                │
│              └─ Posts rich comment on the PR            │
│                                                         │
└─────────────────────────────────────────────────────────┘
         │
         ▼
Developer sees PR comment:
  ✅ "Auto-fix applied! Check the new commit."
  OR
  📋 "Here's your step-by-step solution guide."
```

---

## Step 1: Add Secrets to GitHub

Go to your repo → **Settings** → **Secrets and variables** → **Actions**

Add these **two** secrets:

| Secret Name | Value | Where to get it |
|---|---|---|
| `OPENAI_API_KEY` | `sk-...` | [platform.openai.com](https://platform.openai.com/api-keys) |
| `AGENT_GH_TOKEN` | `ghp_...` | [github.com/settings/tokens](https://github.com/settings/tokens) → classic token |

### Creating `AGENT_GH_TOKEN`

Go to **github.com → Settings → Developer settings → Personal access tokens → Tokens (classic)**
Click **"Generate new token (classic)"** and tick these scopes:

```
✅ repo          — read/write code + PRs
✅ workflow       — trigger + read Actions runs
✅ read:org       — if your repo is in an organisation
```

> **Why not use the built-in `GITHUB_TOKEN`?**
> The default `GITHUB_TOKEN` cannot re-trigger CI workflows (by design, to prevent
> infinite loops). The agent needs a real PAT so it can:
> 1. Push a fix commit → which triggers CI to re-run automatically
> 2. Download logs from other workflow runs
> 3. Post + update PR comments

---

## Step 2: Copy Agent Files to Your Repo

The agent needs **3 things** copied into your target repo:

```bash
# ─── Run this inside your backend / frontend / any repo ───

# 1. The AI agent workflow (triggers on CI failure)
mkdir -p .github/workflows
cp path/to/agent-1/.github/workflows/cicd-agent.yml  .github/workflows/

# 2. The agent Python code
cp -r path/to/agent-1/agent/   ./agent/

# 3. CLI + dependencies
cp path/to/agent-1/main.py      ./main.py
cp path/to/agent-1/requirements.txt ./requirements.txt
```

Then commit and push. That's it — the agent is now live in your repo.

```bash
git add .github/workflows/cicd-agent.yml agent/ main.py requirements.txt
git commit -m "chore: add CI/CD error analysis agent"
git push
```

---

## Step 3: Three Ways to Trigger the Agent

### 🔴 Way 1: Automatic (Recommended for Office Use)

The agent triggers **automatically** when any workflow in your repo fails.

```yaml
# Already in cicd-agent.yml:
on:
  workflow_run:
    workflows: ["*"]   # watches ALL workflows
    types: [completed]
```

**Flow:**
1. Developer pushes code → PR opens
2. Your CI pipeline runs → ❌ fails
3. Agent wakes up → analyzes → fixes → comments on PR

**Nothing to do — it just works after setup.**

---

### 💬 Way 2: Comment `/analyze` on Any PR

On any failing PR, just comment:

```
/analyze
```

Or with a specific run ID:
```
/analyze 12345678901
```

The agent will:
1. Read the PR's changed files
2. Fetch the latest failed run log
3. Analyze and fix

---

### ⚙️ Way 3: Manual Trigger (Paste Error Log)

Go to **Actions** → **🤖 CI/CD Error Analysis Agent** → **Run workflow**

Fill in:
- **Failed workflow run ID** — from the URL of the failed run
- OR **paste your error log** directly into the text box
- Select **platform** (github-actions / jenkins / gitlab)

---

## Step 4: What the Agent Does With Your PR

### Scenario: Developer changes `app/services/user_service.py` and CI fails

```
PR #47: "Add user authentication"
  Changed files:
    - app/services/user_service.py  (+45 -3)
    - app/models/user.py            (+12 -0)
    - requirements.txt              (+1 -0)
```

**Agent's actions:**

```
[09:01:05] Agent started — repo=company/backend-service
[09:01:05] PR #47 detected — reading changed files for context
[09:01:06] PR diff: 3 files changed (+58 -3)
[09:01:06] Starting log analysis
[09:01:07] Parsed 2 error blocks from log
[09:01:09] LLM analysis: root_cause="ImportError in user_service.py line 12"
[09:01:09] affected_files=['app/services/user_service.py']
[09:01:10] Targeting PR #47 branch: feature/user-auth
[09:01:11] Fetched app/services/user_service.py (342 chars)
[09:01:13] LLM generated 1 patch
[09:01:14] Applied patch to app/services/user_service.py
[09:01:14] ✅ Fix committed directly to PR #47 branch 'feature/user-auth'
```

**PR Comment Posted:**

```
## 🤖 CI/CD Error Analysis Agent — Report

✅ Auto-fix applied & PR updated!

### 🔍 Root Cause
ImportError in user_service.py — 'bcrypt' package imported but not in requirements.txt

### 🐛 Detected Errors
1. [IMPORT_ERROR] ModuleNotFoundError: No module named 'bcrypt'
   `app/services/user_service.py:12`

### 🛠️ Fix Strategy
Add 'bcrypt' to requirements.txt and ensure it's imported correctly

---

### ✅ Fix Applied
**Branch:** `feature/user-auth`
**Commit:** Code changes pushed to this PR branch

**Files modified:**
- `requirements.txt`

> ⚡ The CI pipeline will re-run automatically on this branch.
```

---

## Step 5: Multi-Repo Office Setup

For organisations with many repos (backend, frontend, microservices):

### Option A: Central Agent Repo (Recommended)

```
company/
  ├── cicd-agent/          ← This repo (deploy once)
  │   └── .github/workflows/cicd-agent.yml
  │
  ├── backend-service/     ← Just add the cicd-agent.yml workflow
  ├── frontend-app/        ← Just add the cicd-agent.yml workflow
  ├── api-gateway/         ← Just add the cicd-agent.yml workflow
  └── data-pipeline/       ← Just add the cicd-agent.yml workflow
```

Each repo only needs the `cicd-agent.yml` workflow copied in.
The agent code runs from itself (actions/checkout checks out the repo that failed).

### Option B: GitHub App (Enterprise)

Create a GitHub App that installs on all repos:
1. Create app at github.com/settings/apps
2. Grant `contents:write`, `pull_requests:write`, `actions:read`
3. Install on all repos in your org
4. Use the App's token instead of `GITHUB_TOKEN`

---

## Error Types the Agent Handles

| Error | Example | Agent Action |
|---|---|---|
| Wrong package version | `pandas==99.0.0 not found` | Updates `requirements.txt` / `package.json` |
| Missing import | `No module named 'bcrypt'` | Adds to `requirements.txt` + fixes import |
| Syntax error | `SyntaxError: invalid syntax` | Rewrites the broken block |
| Wrong env variable | `KeyError: 'DATABASE_URL'` | Fixes the variable name in code |
| Test assertion failure | `AssertionError: expected X got Y` | Fixes test or the function under test |
| Maven/Gradle build error | `cannot find symbol: UserService` | Adds missing import or creates stub |
| Docker build error | `COPY failed: file not found` | Fixes Dockerfile path |
| Type errors (TypeScript) | `TS2345: Argument of type...` | Fixes the type annotation |
| Linting errors | `flake8: E501 line too long` | Reformats the code |
