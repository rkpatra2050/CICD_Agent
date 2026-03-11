"""
agent/parsers/generic.py
Fallback parser for any CI/CD log format.
"""

from __future__ import annotations

import re
from typing import List

from agent.state import ErrorBlock


class GenericParser:
    """
    A best-effort parser that works with any CI/CD log format.
    Used when the platform is unknown or unsupported.
    """

    # Broad error-signal patterns
    _ERROR_PATTERNS = [
        re.compile(r"\b(ERROR|FAILED|FAILURE|FATAL|Exception|Traceback|SyntaxError)\b"),
        re.compile(r"npm ERR!", re.IGNORECASE),
        re.compile(r"exit(ed)? with code [^0]", re.IGNORECASE),
        re.compile(r"Process completed with exit code [^0]"),
        re.compile(r"command not found", re.IGNORECASE),
        re.compile(r"No such file or directory", re.IGNORECASE),
        re.compile(r"Permission denied", re.IGNORECASE),
        re.compile(r"undefined reference to"),
        re.compile(r"cannot find module", re.IGNORECASE),
    ]

    _FILE_REF_RE = re.compile(r'([\w./\\-]+\.\w+)[:\s(](\d+)')
    # Strip common ANSI codes
    _ANSI_RE = re.compile(r"\x1b\[[0-9;]*[mGKHF]")
    # Strip leading timestamps (various formats)
    _TS_RE = re.compile(
        r"^(?:\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?|\[\d+:\d+:\d+\])\s*"
    )

    def _clean(self, line: str) -> str:
        line = self._ANSI_RE.sub("", line)
        line = self._TS_RE.sub("", line)
        return line.strip()

    def parse(self, log: str) -> List[ErrorBlock]:
        """
        Parse any CI/CD log and return error blocks.

        Args:
            log: Raw log text.

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

                    errors.append(ErrorBlock(
                        error_type=self._classify(line),
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
        if "traceback" in line_lower or "exception" in line_lower:
            return "EXCEPTION"
        if "syntax" in line_lower:
            return "SYNTAX_ERROR"
        if "permission" in line_lower:
            return "PERMISSION_ERROR"
        if "not found" in line_lower or "no such file" in line_lower:
            return "FILE_NOT_FOUND"
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
