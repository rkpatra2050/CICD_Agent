"""
agent/parsers/jenkins.py
Parser for Jenkins build console output logs.
"""

from __future__ import annotations

import re
from typing import List

from agent.state import ErrorBlock


class JenkinsParser:
    """
    Parses Jenkins pipeline / freestyle build console logs.

    Jenkins logs have no consistent timestamp format across plugins.
    Common error indicators: '[ERROR]', 'BUILD FAILURE', exception stack
    traces, Maven/Gradle/npm/Python specific failure messages.
    """

    _ERROR_PATTERNS = [
        re.compile(r"\[ERROR\]\s*(.+)"),
        re.compile(r"BUILD FAILURE", re.IGNORECASE),
        re.compile(r"FATAL:\s*(.+)", re.IGNORECASE),
        re.compile(r"Exception in thread"),
        re.compile(r"Traceback \(most recent call last\)"),
        re.compile(r"npm ERR!", re.IGNORECASE),
        re.compile(r"ERROR:\s*.+"),
        re.compile(r"FAILED\s*$"),
        re.compile(r"error TS\d+:"),           # TypeScript errors
        re.compile(r"error\[E\d+\]"),           # Rust errors
        re.compile(r"cannot find symbol"),       # Java
        re.compile(r"undefined reference to"),   # C/C++
        re.compile(r"No module named"),
        re.compile(r"hudson\..*?Exception"),     # Jenkins-specific exceptions
    ]

    _FILE_REF_RE = re.compile(r'([\w/.\\-]+\.(?:java|py|js|ts|go|rb|cs|cpp|c|h|xml|yml|yaml|json|sh))[\[:\s(]\[?(\d+)', re.IGNORECASE)

    def parse(self, log: str) -> List[ErrorBlock]:
        """
        Parse Jenkins console output and return error blocks.

        Args:
            log: Raw Jenkins build console log text.

        Returns:
            List of ErrorBlock instances.
        """
        errors: List[ErrorBlock] = []
        lines = log.splitlines()
        context_window = 12

        i = 0
        while i < len(lines):
            line = lines[i]
            for pattern in self._ERROR_PATTERNS:
                if pattern.search(line):
                    ctx_start = max(0, i - context_window)
                    ctx_end = min(len(lines), i + context_window + 1)
                    block = lines[ctx_start:ctx_end]
                    block_text = "\n".join(block)

                    # Extend forward to capture file references that appear after
                    # the trigger line (e.g., Maven prints errors after BUILD FAILURE)
                    extended_end = min(len(lines), i + context_window * 2 + 1)
                    extended_block = "\n".join(lines[ctx_start:extended_end])

                    file_path, line_no = self._extract_file_ref(extended_block)
                    error_type = self._classify(line)

                    errors.append(ErrorBlock(
                        error_type=error_type,
                        message=line.strip(),
                        file_path=file_path,
                        line_number=line_no,
                        context=block_text,
                        raw_snippet=block_text,
                    ))
                    i += context_window
                    break
            i += 1

        return self._deduplicate(errors)

    def _classify(self, line: str) -> str:
        """Return a short error-type label."""
        line_lower = line.lower()
        if "build failure" in line_lower:
            return "BUILD_FAILURE"
        if "npm err" in line_lower:
            return "NPM_ERROR"
        if "traceback" in line_lower or "exception" in line_lower:
            return "EXCEPTION"
        if "no module named" in line_lower:
            return "IMPORT_ERROR"
        if "cannot find symbol" in line_lower:
            return "COMPILATION_ERROR"
        if "hudson" in line_lower:
            return "JENKINS_ERROR"
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
