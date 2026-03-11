#!/usr/bin/env python3
"""
real_world_demo.py
Demonstrates exactly what the agent does step-by-step in a real scenario.
Run this to understand the agent's decision flow without needing real API keys.
"""

from agent.state import AgentState, ErrorBlock
from agent.parsers.github_actions import GitHubActionsParser

# ── SIMULATE: a real GitHub Actions log ──────────────────────────────────────
REAL_FAILED_LOG = """
2026-03-10T09:01:00.000Z ##[group]Run pip install -r requirements.txt
2026-03-10T09:01:01.123Z Collecting flask==2.3.0
2026-03-10T09:01:02.456Z Collecting numpy==1.26.0
2026-03-10T09:01:03.789Z ##[error]ERROR: Could not find a version that satisfies the requirement pandas==99.0.0 (from versions: 0.1, ..., 2.2.1)
2026-03-10T09:01:03.790Z ##[error]ERROR: No matching distribution found for pandas==99.0.0
2026-03-10T09:01:03.800Z ##[endgroup]
2026-03-10T09:01:04.000Z ##[group]Run python -m pytest tests/ -v
2026-03-10T09:01:04.100Z ============================= test session starts ==============================
2026-03-10T09:01:04.200Z FAILED tests/test_data.py::test_load_data - ModuleNotFoundError: No module named 'pandas'
2026-03-10T09:01:04.300Z ========================= 1 failed in 0.08s ==========================
2026-03-10T09:01:04.310Z ##[error]Process completed with exit code 1
"""

def demo_step1_parse():
    """STEP 1: The parser extracts structured errors from raw logs."""
    print("\n" + "="*60)
    print("STEP 1: PARSING THE CI/CD LOG")
    print("="*60)

    parser = GitHubActionsParser()
    errors = parser.parse(REAL_FAILED_LOG)

    print(f"\n✅ Found {len(errors)} error(s):\n")
    for i, err in enumerate(errors, 1):
        print(f"  Error #{i}")
        print(f"    Type    : {err.error_type}")
        print(f"    Message : {err.message[:80]}")
        print(f"    File    : {err.file_path or 'N/A'}")
        print(f"    Line    : {err.line_number or 'N/A'}")
        print()

    return errors


def demo_step2_llm_analysis():
    """STEP 2: Explain what the LLM would produce for root-cause analysis."""
    print("\n" + "="*60)
    print("STEP 2: LLM ROOT-CAUSE ANALYSIS (GPT-4)")
    print("="*60)

    simulated_llm_response = {
        "root_cause": "requirements.txt specifies a non-existent version pandas==99.0.0",
        "error_types": ["DEPENDENCY_ERROR", "IMPORT_ERROR"],
        "affected_files": ["requirements.txt"],
        "fix_strategy": (
            "1. Open requirements.txt\n"
            "2. Find the line 'pandas==99.0.0'\n"
            "3. Replace with the latest stable version 'pandas==2.2.1'\n"
            "4. Commit and push — the pipeline will retry automatically"
        ),
        "confidence": "high",
        "requires_human_review": False,
        "notes": "The package pandas does not have a version 99.0.0. "
                 "Latest stable is 2.2.1 as of March 2026.",
    }

    print("\n🤖 GPT-4 Analysis Result:")
    print(f"\n  Root Cause  : {simulated_llm_response['root_cause']}")
    print(f"  Confidence  : {simulated_llm_response['confidence']}")
    print(f"  Needs Human : {simulated_llm_response['requires_human_review']}")
    print(f"  Affected    : {simulated_llm_response['affected_files']}")
    print(f"\n  Fix Strategy:\n")
    for line in simulated_llm_response["fix_strategy"].split("\n"):
        print(f"    {line}")

    return simulated_llm_response


def demo_step3_patch():
    """STEP 3: Show the patch GPT-4 would generate."""
    print("\n" + "="*60)
    print("STEP 3: AUTO-PATCH GENERATION")
    print("="*60)

    print("\n📄 Current requirements.txt (fetched from GitHub):")
    print("  ┌─────────────────────────────┐")
    print("  │ flask==2.3.0                │")
    print("  │ numpy==1.26.0               │")
    print("  │ pandas==99.0.0   ← ❌ BAD  │")
    print("  │ pytest==8.0.0               │")
    print("  └─────────────────────────────┘")

    print("\n🤖 GPT-4 generated patch:")
    print("  original_snippet : 'pandas==99.0.0'")
    print("  fixed_snippet    : 'pandas==2.2.1'")
    print("  explanation      : 'pandas 99.0.0 does not exist; pinning to latest stable 2.2.1'")

    print("\n📄 Patched requirements.txt (committed to fix branch):")
    print("  ┌─────────────────────────────┐")
    print("  │ flask==2.3.0                │")
    print("  │ numpy==1.26.0               │")
    print("  │ pandas==2.2.1    ← ✅ FIXED│")
    print("  │ pytest==8.0.0               │")
    print("  └─────────────────────────────┘")


def demo_step4_pr():
    """STEP 4: Show what the PR looks like."""
    print("\n" + "="*60)
    print("STEP 4: PULL REQUEST RAISED AUTOMATICALLY")
    print("="*60)

    print("""
  Branch  : cicd-autofix/missing-dependency-pandas-20260310T090105
  PR #    : 42
  Title   : fix(cicd): auto-remediate pipeline failure — requirements.txt specifies a non-existent version

  PR Body:
  ┌──────────────────────────────────────────────────────────┐
  │ ## 🤖 Automated CI/CD Fix                               │
  │                                                          │
  │ **Root Cause:** requirements.txt specifies a             │
  │ non-existent version pandas==99.0.0                      │
  │                                                          │
  │ **Errors Detected:**                                     │
  │ - [DEPENDENCY_ERROR] Could not find pandas==99.0.0       │
  │ - [IMPORT_ERROR] No module named 'pandas'                │
  │                                                          │
  │ **Files Modified:**                                      │
  │ - `requirements.txt`                                     │
  │                                                          │
  │ **How to verify:**                                       │
  │ 1. This PR will trigger the CI pipeline automatically    │
  │ 2. Confirm the pip install step now passes               │
  │ 3. Confirm all tests pass                                │
  └──────────────────────────────────────────────────────────┘

  URL: https://github.com/your-org/your-repo/pull/42
""")


def demo_step5_fallback():
    """STEP 5: Show fallback when auto-fix isn't possible."""
    print("\n" + "="*60)
    print("STEP 5: FALLBACK — SOLUTION GUIDE (when auto-fix fails)")
    print("="*60)

    print("""
  If the agent cannot auto-fix (e.g., requires_human_review=True,
  or the patch target wasn't found), it outputs this instead:

  ┌──────────────────────────────────────────────────────────┐
  │ # CI/CD Pipeline Error — Remediation Guide              │
  │                                                          │
  │ ## Problem Summary                                       │
  │ Your pip install step failed because requirements.txt    │
  │ references pandas==99.0.0, which does not exist on PyPI. │
  │                                                          │
  │ ## Root Cause                                            │
  │ The version 99.0.0 of pandas has never been released.    │
  │ The latest stable is 2.2.1.                              │
  │                                                          │
  │ ## Step-by-Step Fix                                      │
  │ 1. Open requirements.txt                                 │
  │ 2. Change:  pandas==99.0.0                               │
  │    To:      pandas==2.2.1                                │
  │ 3. Commit:  git commit -am "fix: update pandas version"  │
  │ 4. Push:    git push                                      │
  │                                                          │
  │ ## Verification                                          │
  │ Run locally:  pip install -r requirements.txt            │
  │               python -m pytest tests/                    │
  │                                                          │
  │ ## Prevention                                            │
  │ - Use dependabot or renovate to keep versions updated    │
  │ - Pin to minor versions (pandas>=2.2,<3) not exact patch │
  └──────────────────────────────────────────────────────────┘
""")


if __name__ == "__main__":
    print("\n🤖 CI/CD Pipeline Error Analysis Agent — Real World Demo")
    print("   Simulating a failed GitHub Actions run...")

    errors = demo_step1_parse()
    analysis = demo_step2_llm_analysis()
    demo_step3_patch()
    demo_step4_pr()
    demo_step5_fallback()

    print("\n" + "="*60)
    print("SUMMARY: What the real `python main.py analyze` command does")
    print("="*60)
    print("""
  python main.py analyze \\
    --repo your-org/your-repo \\
    --run-id 12345678901 \\
    --platform github-actions

  1. ✅ Fetches the failed run log from GitHub automatically
  2. ✅ Parses all error blocks with context
  3. ✅ Calls GPT-4 for root-cause analysis
  4. ✅ Creates branch: cicd-autofix/<cause>-<timestamp>
  5. ✅ Fetches affected files from your repo
  6. ✅ GPT-4 generates minimal code patches
  7. ✅ Commits patches to the fix branch
  8. ✅ Opens a Pull Request with full description
  9. 🔄 Fallback: Prints solution guide if steps 4-8 fail
""")
