# CI/CD Pipeline Error Analysis AI Agent

## Project Overview
This is an AI-powered agent that:
1. Analyzes CI/CD pipeline errors (GitHub Actions, Jenkins, GitLab CI, etc.)
2. Generates appropriate fixes using LLM reasoning
3. Applies code changes to the repository
4. Raises Pull Requests with the fixes automatically
5. Falls back to providing detailed solution guidance if auto-fix fails

## Tech Stack
- **Language**: Python 3.10+
- **AI Framework**: LangChain + OpenAI GPT-4
- **GitHub Integration**: PyGithub
- **CLI**: Click
- **Config**: python-dotenv

## Key Modules
- `agent/core.py` — Main agent orchestration loop
- `agent/tools/` — LangChain tools (log parser, file editor, git ops, PR creator)
- `agent/llm.py` — LLM setup and prompt templates
- `agent/github_client.py` — GitHub API wrapper
- `agent/parsers/` — CI log parsers (GitHub Actions, Jenkins, GitLab)
- `main.py` — Entry point CLI

## Development Rules
- Always use environment variables for secrets (never hardcode tokens)
- Follow PEP 8 style conventions
- Add docstrings to all public functions and classes
- Handle all GitHub API errors gracefully
- Log all agent actions for auditability
