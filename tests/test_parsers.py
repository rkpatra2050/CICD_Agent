"""
tests/test_parsers.py
Unit tests for all CI/CD log parsers.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.parsers.github_actions import GitHubActionsParser
from agent.parsers.jenkins import JenkinsParser
from agent.parsers.gitlab_ci import GitLabCIParser
from agent.parsers.generic import GenericParser

FIXTURES = Path(__file__).parent / "fixtures" / "sample_logs"


class TestGitHubActionsParser:
    """Tests for the GitHub Actions log parser."""

    def setup_method(self):
        self.parser = GitHubActionsParser()
        self.log = (FIXTURES / "github_actions_pip_error.log").read_text()

    def test_detects_errors(self):
        errors = self.parser.parse(self.log)
        assert len(errors) >= 1, "Should detect at least one error"

    def test_error_types(self):
        errors = self.parser.parse(self.log)
        types = [e.error_type for e in errors]
        assert any(t in ("GHA_ERROR", "IMPORT_ERROR", "GENERIC_ERROR") for t in types)

    def test_error_message_not_empty(self):
        errors = self.parser.parse(self.log)
        for err in errors:
            assert err.message.strip(), "Error message should not be empty"

    def test_context_present(self):
        errors = self.parser.parse(self.log)
        for err in errors:
            assert err.context, "Error context should be populated"

    def test_deduplication(self):
        """Parsing the same log twice should not double the errors."""
        errors1 = self.parser.parse(self.log)
        errors2 = self.parser.parse(self.log)
        assert len(errors1) == len(errors2)

    def test_empty_log(self):
        errors = self.parser.parse("")
        assert errors == [], "Empty log should yield no errors"

    def test_clean_log(self):
        clean_log = "Everything passed successfully.\nAll tests green.\n"
        errors = self.parser.parse(clean_log)
        assert errors == [], "Clean log should yield no errors"


class TestJenkinsParser:
    """Tests for the Jenkins log parser."""

    def setup_method(self):
        self.parser = JenkinsParser()
        self.log = (FIXTURES / "jenkins_maven_error.log").read_text()

    def test_detects_build_failure(self):
        errors = self.parser.parse(self.log)
        assert any("BUILD_FAILURE" in e.error_type or "COMPILATION_ERROR" in e.error_type
                   for e in errors), "Should detect BUILD FAILURE or COMPILATION_ERROR"

    def test_extracts_file_reference(self):
        errors = self.parser.parse(self.log)
        file_refs = [e.file_path for e in errors if e.file_path]
        # Maven log contains src/main/java/com/example/App.java:[25,18]
        assert any(f and "App.java" in f for f in file_refs), (
            "Should extract file path from Maven error"
        )

    def test_error_messages_non_empty(self):
        errors = self.parser.parse(self.log)
        assert all(e.message.strip() for e in errors)


class TestGitLabCIParser:
    """Tests for the GitLab CI log parser."""

    def setup_method(self):
        self.parser = GitLabCIParser()
        self.log = (FIXTURES / "gitlab_npm_error.log").read_text()

    def test_detects_npm_error(self):
        errors = self.parser.parse(self.log)
        assert len(errors) >= 1, "Should detect npm ERR!"

    def test_strips_ansi(self):
        ansi_log = "\x1b[31mERROR: something went wrong\x1b[0m"
        errors = self.parser.parse(ansi_log)
        assert errors, "Should parse ANSI-colored log"
        assert "\x1b" not in errors[0].message, "ANSI codes should be stripped"

    def test_strips_section_markers(self):
        log_with_sections = (
            "section_start:1234567890:my_step\r\n"
            "ERROR: Job failed\n"
            "section_end:1234567890:my_step\r\n"
        )
        errors = self.parser.parse(log_with_sections)
        assert errors, "Should parse log with section markers"
        assert "section_" not in errors[0].message


class TestGenericParser:
    """Tests for the generic/fallback log parser."""

    def setup_method(self):
        self.parser = GenericParser()

    def test_detects_traceback(self):
        log = (
            "Running tests...\n"
            "Traceback (most recent call last):\n"
            '  File "app.py", line 42, in <module>\n'
            "    raise ValueError('something broke')\n"
            "ValueError: something broke\n"
        )
        errors = self.parser.parse(log)
        assert errors, "Should detect Python traceback"
        assert any(e.error_type == "EXCEPTION" for e in errors)

    def test_detects_command_not_found(self):
        log = "bash: mycommand: command not found\nexit code 127\n"
        errors = self.parser.parse(log)
        assert errors

    def test_clean_log_no_errors(self):
        log = "Build completed successfully.\nAll 42 tests passed.\n"
        errors = self.parser.parse(log)
        assert errors == []

    def test_strips_timestamps(self):
        log = "2024-05-10T12:00:00Z ERROR: something failed\n"
        errors = self.parser.parse(log)
        assert errors
        assert "2024-05-10" not in errors[0].message

    def test_deduplication_prevents_explosion(self):
        """Repeated error lines should not produce dozens of entries."""
        repeated = "ERROR: disk full\n" * 50
        errors = self.parser.parse(repeated)
        assert len(errors) <= 5, f"Too many duplicate errors: {len(errors)}"
