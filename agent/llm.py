"""
agent/llm.py
LLM initialisation and structured prompt templates for the CI/CD agent.
"""

from __future__ import annotations

import os
from typing import Any, Dict

from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate


# ── LLM singleton ───────────────────────────────────────────────────────────

def get_llm(temperature: float = 0.0) -> ChatOpenAI:
    """
    Return a configured ChatOpenAI instance.

    Args:
        temperature: Sampling temperature (0 = deterministic).

    Returns:
        ChatOpenAI instance ready for invocation.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "OPENAI_API_KEY is not set. "
            "Copy .env.example to .env and add your key."
        )
    model = os.getenv("OPENAI_MODEL", "gpt-4o")
    return ChatOpenAI(
        model=model,
        temperature=temperature,
        openai_api_key=api_key,
    )


# ── Prompt templates ────────────────────────────────────────────────────────

ANALYZE_SYSTEM = """You are an expert DevOps and Software Engineering AI assistant \
specialised in diagnosing CI/CD pipeline failures across GitHub Actions, Jenkins, \
GitLab CI, and CircleCI.

Your job:
1. Read the CI/CD log provided by the user.
2. If a PR diff is provided, examine EXACTLY what code the developer changed.
3. Identify ALL errors, their root causes (especially linking them to the PR changes), \
   and the affected files / lines.
4. Suggest a clear, actionable fix strategy.

Always respond in valid JSON matching exactly this schema:
{{
  "root_cause": "<one-sentence summary — if diff provided, relate cause to the change>",
  "error_types": ["<type1>", "<type2>"],
  "affected_files": ["<path1>", "<path2>"],
  "fix_strategy": "<detailed multi-step strategy>",
  "confidence": "<high|medium|low>",
  "requires_human_review": <true|false>,
  "notes": "<any extra context>"
}}"""

ANALYZE_HUMAN = """Platform: {platform}
Repository: {repo}

=== CI/CD LOG (truncated to 12 000 chars) ===
{log}
==============================================

{pr_diff_section}

Analyse the above and return the JSON object."""


GENERATE_FIX_SYSTEM = """You are an expert software engineer. \
You will receive:
- A root-cause analysis of a CI/CD failure
- The current contents of one or more source files
- A fix strategy

Your task:
1. Produce the minimal, correct code changes needed to resolve the errors.
2. Return a JSON array of file patches.

Always respond in valid JSON matching exactly this schema:
{{
  "patches": [
    {{
      "file_path": "<relative path in repo>",
      "original_snippet": "<exact substring to replace (3+ lines of context)>",
      "fixed_snippet": "<replacement code>",
      "explanation": "<why this fixes the error>"
    }}
  ],
  "commit_message": "<conventional-commit style message>",
  "pr_title": "<concise PR title>",
  "pr_body": "<detailed markdown PR description with problem, fix, and testing notes>"
}}"""

GENERATE_FIX_HUMAN = """Root Cause: {root_cause}
Fix Strategy: {fix_strategy}
Affected Files: {affected_files}

=== FILE CONTENTS ===
{file_contents}
=====================

Generate the patches JSON."""


SOLUTION_GUIDE_SYSTEM = """You are a senior DevOps engineer writing a clear, \
step-by-step remediation guide for a CI/CD failure that could NOT be auto-fixed.

The guide must be in Markdown and include:
1. **Problem Summary** – what went wrong and why
2. **Root Cause** – technical explanation
3. **Step-by-Step Fix** – numbered list with code blocks where applicable
4. **Verification** – how to confirm the fix works
5. **Prevention** – how to avoid the same issue in future
"""

SOLUTION_GUIDE_HUMAN = """Platform: {platform}
Repository: {repo}
Root Cause: {root_cause}
Fix Strategy: {fix_strategy}
Errors:
{errors}

Write the remediation guide."""


# ── Prompt builders ──────────────────────────────────────────────────────────

def build_analyze_prompt() -> ChatPromptTemplate:
    """Return the log-analysis prompt template."""
    return ChatPromptTemplate.from_messages([
        SystemMessagePromptTemplate.from_template(ANALYZE_SYSTEM),
        HumanMessagePromptTemplate.from_template(ANALYZE_HUMAN),
    ])


def build_fix_prompt() -> ChatPromptTemplate:
    """Return the fix-generation prompt template."""
    return ChatPromptTemplate.from_messages([
        SystemMessagePromptTemplate.from_template(GENERATE_FIX_SYSTEM),
        HumanMessagePromptTemplate.from_template(GENERATE_FIX_HUMAN),
    ])


def build_solution_guide_prompt() -> ChatPromptTemplate:
    """Return the fallback solution-guide prompt template."""
    return ChatPromptTemplate.from_messages([
        SystemMessagePromptTemplate.from_template(SOLUTION_GUIDE_SYSTEM),
        HumanMessagePromptTemplate.from_template(SOLUTION_GUIDE_HUMAN),
    ])


def invoke_json_llm(
    llm: ChatOpenAI,
    prompt: ChatPromptTemplate,
    variables: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Invoke the LLM with a prompt, parse its response as JSON.

    Args:
        llm: The ChatOpenAI instance.
        prompt: The prompt template.
        variables: Template variables.

    Returns:
        Parsed JSON dict from the model response.

    Raises:
        ValueError: If the response cannot be parsed as JSON.
    """
    import json
    import re

    chain = prompt | llm
    response = chain.invoke(variables)
    content = response.content.strip()

    # Strip markdown fences if present
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)

    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"LLM response was not valid JSON:\n{content}"
        ) from exc
