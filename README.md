# CI/CD Pipeline Error Analysis AI Agent

An AI-powered agent that analyzes CI/CD pipeline failures, automatically generates and applies fixes, raises Pull Requests, and provides detailed solution guidance when auto-fix isn't possible.

---

## Features

- 🔍 **Multi-Platform Log Parsing** — Supports GitHub Actions, Jenkins, GitLab CI, CircleCI
- 🤖 **AI-Powered Root Cause Analysis** — Uses GPT-4 to understand complex build failures
- 🛠️ **Automatic Code Remediation** — Edits source files to fix identified issues
- 🔀 **Automated PR Creation** — Commits fixes and opens a Pull Request with full description
- 📋 **Fallback Solution Guide** — Provides step-by-step solutions when auto-fix isn't feasible
- 📊 **Rich Audit Logs** — Every agent action is logged for traceability

---

## Architecture

```
agent-1/
├── main.py                    # CLI entry point
├── agent/
│   ├── core.py                # Main agent orchestration
│   ├── llm.py                 # LLM setup & prompt templates
│   ├── github_client.py       # GitHub API wrapper
│   ├── state.py               # Agent state management
│   ├── tools/
│   │   ├── log_analyzer.py    # Parse & analyze CI logs
│   │   ├── file_editor.py     # Read/write repository files
│   │   ├── git_operations.py  # Branch, commit, push
│   │   ├── pr_creator.py      # Create GitHub Pull Requests
│   │   └── solution_writer.py # Fallback solution generator
│   └── parsers/
│       ├── github_actions.py  # GitHub Actions log parser
│       ├── jenkins.py         # Jenkins log parser
│       ├── gitlab_ci.py       # GitLab CI log parser
│       └── generic.py        # Generic/fallback parser
├── prompts/
│   ├── analyze_error.txt      # Error analysis prompt
│   ├── generate_fix.txt       # Fix generation prompt
│   └── pr_description.txt     # PR description prompt
├── tests/
│   ├── test_parsers.py
│   ├── test_agent.py
│   └── fixtures/
│       └── sample_logs/
├── .env.example               # Environment variable template
├── requirements.txt
└── README.md
```

---

## Quick Start

### 1. Clone and Install

```bash
git clone <repo-url>
cd agent-1
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your tokens
```

### 3. Run the Agent

```bash
# Analyze a failed GitHub Actions run
python main.py analyze \
  --repo owner/repository \
  --run-id 1234567890 \
  --platform github-actions

# Analyze from a log file
python main.py analyze \
  --repo owner/repository \
  --log-file path/to/build.log \
  --platform jenkins

# Analyze a GitLab CI pipeline
python main.py analyze \
  --repo owner/repository \
  --pipeline-id 987654 \
  --platform gitlab
```

---

## Environment Variables

| Variable | Description | Required |
|---|---|---|
| `OPENAI_API_KEY` | OpenAI API key (GPT-4) | ✅ |
| `GITHUB_TOKEN` | GitHub Personal Access Token (repo + PR scope) | ✅ |
| `GITLAB_TOKEN` | GitLab Personal Access Token | Only for GitLab |
| `JENKINS_URL` | Jenkins server URL | Only for Jenkins |
| `JENKINS_USER` | Jenkins username | Only for Jenkins |
| `JENKINS_API_TOKEN` | Jenkins API token | Only for Jenkins |
| `DEFAULT_BASE_BRANCH` | Base branch for PRs (default: `main`) | ❌ |
| `MAX_FIX_ATTEMPTS` | Max auto-fix attempts (default: `3`) | ❌ |
| `LOG_LEVEL` | Logging level (default: `INFO`) | ❌ |

---

## How It Works

```
CI/CD Log Input
      │
      ▼
┌─────────────┐
│ Log Parser  │  ← Platform-specific parsing
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ LLM Analysis│  ← Root cause identification
└──────┬──────┘
       │
       ▼
┌─────────────────┐
│ Fix Generation  │  ← Code change suggestions
└────────┬────────┘
         │
    ┌────┴────┐
    │         │
    ▼         ▼
┌───────┐  ┌──────────────┐
│Auto   │  │ Solution      │
│Fix &  │  │ Guide Output  │
│PR     │  │ (Fallback)    │
└───────┘  └──────────────┘
```

---

## Agent Decision Flow

1. **Parse** CI/CD log to extract error blocks, stack traces, and context
2. **Analyze** errors with GPT-4 to determine root cause and fix strategy
3. **Attempt** automated code fixes (up to `MAX_FIX_ATTEMPTS` iterations)
4. **Validate** fixes by re-analyzing the changed code
5. **Create PR** with detailed description, affected files, and test suggestions
6. **Fallback**: If auto-fix fails, output a structured solution guide

---

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Commit your changes
4. Push and open a PR

---

## License

MIT
