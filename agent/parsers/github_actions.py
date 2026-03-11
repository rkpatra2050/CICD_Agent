"""
agent/parsers/github_actions.py
Parser for GitHub Actions workflow run logs.
"""

from __future__ import annotations

import re
from typing import List

from agent.state import ErrorBlock


class GitHubActionsParser:
    """
    Parses raw GitHub Actions log output to extract error blocks.

    GitHub Actions logs are structured as:
        YYYY-MM-DDTHH:MM:SS.ffffffZ <level> <message>

    Error indicators include lines with '##[error]', 'Error:', 'FAILED',
    exception stack traces, and build-tool specific patterns (npm, pytest,
    gradle, maven, etc.).
    """

    # Timestamp prefix common to GHA log lines
    _TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z\s+")

    # GHA native error annotation
    _GHA_ERROR_RE = re.compile(r"##\[error\](.*)", re.IGNORECASE)

    # Generic error patterns (file path + line optional)
    _ERROR_PATTERNS = [
        re.compile(r"(?:Error|ERROR|FAILED|FAILURE|fatal|FATAL)[:\s](.+)", re.IGNORECASE),
        re.compile(r"Exception in thread", re.IGNORECASE),
        re.compile(r"Traceback \(most recent call last\)", re.IGNORECASE),
        re.compile(r"npm ERR!", re.IGNORECASE),
        re.compile(r"ModuleNotFoundError|ImportError|SyntaxError|TypeError|AttributeError"),
        re.compile(r"BUILD FAILURE", re.IGNORECASE),
        re.compile(r"AssertionError|PermissionError|FileNotFoundError"),
        re.compile(r"TESTS FAILED|test.*FAILED", re.IGNORECASE),
        re.compile(r"Process completed with exit code [^0]"),
    ]

    # File-reference pattern: path:line
    _FILE_REF_RE = re.compile(r'([\w./\\-]+\.\w+):(\d+)')

    def _strip_ts(self, line: str) -> str:
        """Remove the GHA timestamp prefix from a log line."""
        return self._TS_RE.sub("", line)

    def parse(self, log: str) -> List[ErrorBlock]:
        """
        Parse a GitHub Actions log and return a list of ErrorBlock objects.

        Args:
            log: Raw log text from a GitHub Actions workflow run.

        Returns:
            List of ErrorBlock instances representing each detected error.
        """
        errors: List[ErrorBlock] = []
        lines = log.splitlines()
        i = 0
        context_window = 10  # lines before/after error to include as context

        while i < len(lines):
            raw_line = lines[i]
            line = self._strip_ts(raw_line)

            matched = False

            # --- GHA native ##[error] annotation ---
            m = self._GHA_ERROR_RE.search(line)
            if m:
                message = m.group(1).strip()
                ctx_start = max(0, i - context_window)
                ctx_end = min(len(lines), i + context_window + 1)
                context_lines = [self._strip_ts(l) for l in lines[ctx_start:ctx_end]]

                file_path, line_no = self._extract_file_ref(message)

                errors.append(ErrorBlock(
                    error_type="GHA_ERROR",
                    message=message,
                    file_path=file_path,
                    line_number=line_no,
                    context="\n".join(context_lines),
                    raw_snippet="\n".join(lines[ctx_start:ctx_end]),
                ))
                matched = True

            # --- Generic error patterns ---
            if not matched:
                for pattern in self._ERROR_PATTERNS:
                    if pattern.search(line):
                        # Collect the surrounding block
                        ctx_start = max(0, i - context_window)
                        ctx_end = min(len(lines), i + context_window + 1)
                        block = lines[ctx_start:ctx_end]
                        block_text = "\n".join(self._strip_ts(l) for l in block)

                        error_type = self._classify(line)
                        file_path, line_no = self._extract_file_ref(block_text)

                        errors.append(ErrorBlock(
                            error_type=error_type,
                            message=line.strip(),
                            file_path=file_path,
                            line_number=line_no,
                            context=block_text,
                            raw_snippet="\n".join(block),
                        ))
                        i += context_window  # skip ahead to avoid duplicates
                        matched = True
                        break

            i += 1

        return self._deduplicate(errors)

    def _classify(self, line: str) -> str:
        """Return a short error-type label for a log line."""
        line_lower = line.lower()
        if "modulenotfounderror" in line_lower or "importerror" in line_lower:
            return "IMPORT_ERROR"
        if "syntaxerror" in line_lower:
            return "SYNTAX_ERROR"
        if "npm err" in line_lower:
            return "NPM_ERROR"
        if "build failure" in line_lower:
            return "BUILD_FAILURE"
        if "test" in line_lower and "failed" in line_lower:
            return "TEST_FAILURE"
        if "traceback" in line_lower or "exception" in line_lower:
            return "EXCEPTION"
        if "permission" in line_lower:
            return "PERMISSION_ERROR"
        return "GENERIC_ERROR"

    def _extract_file_ref(self, text: str):
        """Extract the first file path + line number from a text block."""
        m = self._FILE_REF_RE.search(text)
        if m:
            return m.group(1), int(m.group(2))
        return None, None

    def _deduplicate(self, errors: List[ErrorBlock]) -> List[ErrorBlock]:
        """Remove near-duplicate error blocks (same message prefix)."""
        seen: set = set()
        unique: List[ErrorBlock] = []
        for err in errors:
            key = err.message[:80]
            if key not in seen:
                seen.add(key)
                unique.append(err)
        return unique
