"""
agent/parsers/gitlab_ci.py
Parser for GitLab CI/CD pipeline job logs.
"""

from __future__ import annotations

import re
from typing import List

from agent.state import ErrorBlock


class GitLabCIParser:
    """
    Parses GitLab CI/CD job logs.

    GitLab CI logs include ANSI colour codes and section markers:
        section_start:<ts>:<name>
        section_end:<ts>:<name>
    We strip those before analysing.
    """

    # ANSI escape code stripper
    _ANSI_RE = re.compile(r"\x1b\[[0-9;]*[mGKHF]")
    # GitLab section markers
    _SECTION_RE = re.compile(r"section_(start|end):\d+:\S+\r?")

    _ERROR_PATTERNS = [
        re.compile(r"ERROR:\s*(.+)", re.IGNORECASE),
        re.compile(r"FAILED\b"),
        re.compile(r"error:\s*.+"),
        re.compile(r"Traceback \(most recent call last\)"),
        re.compile(r"Exception in thread"),
        re.compile(r"npm ERR!"),
        re.compile(r"fatal:\s*.+", re.IGNORECASE),
        re.compile(r"No such file or directory"),
        re.compile(r"Permission denied"),
        re.compile(r"command not found"),
        re.compile(r"exit code \d+", re.IGNORECASE),
        re.compile(r"Job failed"),
    ]

    _FILE_REF_RE = re.compile(r'([\w./\\-]+\.\w+)[:\s(](\d+)')

    def _clean(self, line: str) -> str:
        """Strip ANSI codes and GitLab section markers from a line."""
        line = self._ANSI_RE.sub("", line)
        line = self._SECTION_RE.sub("", line)
        return line.strip()

    def parse(self, log: str) -> List[ErrorBlock]:
        """
        Parse GitLab CI job log and return error blocks.

        Args:
            log: Raw GitLab CI job log text (may include ANSI codes).

        Returns:
            List of ErrorBlock instances.
        """
        errors: List[ErrorBlock] = []
        lines = log.splitlines()
        cleaned = [self._clean(l) for l in lines]
        context_window = 10

        i = 0
        while i < len(cleaned):
            line = cleaned[i]
            for pattern in self._ERROR_PATTERNS:
                if pattern.search(line):
                    ctx_start = max(0, i - context_window)
                    ctx_end = min(len(cleaned), i + context_window + 1)
                    block_text = "\n".join(cleaned[ctx_start:ctx_end])
                    raw_block = "\n".join(lines[ctx_start:ctx_end])

                    file_path, line_no = self._extract_file_ref(block_text)
                    error_type = self._classify(line)

                    errors.append(ErrorBlock(
                        error_type=error_type,
                        message=line,
                        file_path=file_path,
                        line_number=line_no,
                        context=block_text,
                        raw_snippet=raw_block,
                    ))
                    i += context_window
                    break
            i += 1

        return self._deduplicate(errors)

    def _classify(self, line: str) -> str:
        line_lower = line.lower()
        if "job failed" in line_lower:
            return "JOB_FAILURE"
        if "permission denied" in line_lower:
            return "PERMISSION_ERROR"
        if "command not found" in line_lower:
            return "COMMAND_NOT_FOUND"
        if "no such file" in line_lower:
            return "FILE_NOT_FOUND"
        if "traceback" in line_lower or "exception" in line_lower:
            return "EXCEPTION"
        return "GENERIC_ERROR"

    def _extract_file_ref(self, text: str):
        m = self._FILE_REF_RE.search(text)
        if m:
            return m.group(1), int(m.group(2))
        return None, None

    def _deduplicate(self, errors: List[ErrorBlock]) -> List[ErrorBlock]:
        seen: set = set()
        unique: List[ErrorBlock] = []
        for err in errors:
            key = err.message[:80]
            if key not in seen:
                seen.add(key)
                unique.append(err)
        return unique
