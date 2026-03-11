"""
agent/parsers/__init__.py
CI/CD log parser registry.
"""

from .github_actions import GitHubActionsParser
from .jenkins import JenkinsParser
from .gitlab_ci import GitLabCIParser
from .generic import GenericParser

PARSERS = {
    "github-actions": GitHubActionsParser,
    "jenkins": JenkinsParser,
    "gitlab": GitLabCIParser,
    "generic": GenericParser,
}


def get_parser(platform: str):
    """
    Return the appropriate log parser for the given CI/CD platform.

    Args:
        platform: One of 'github-actions', 'jenkins', 'gitlab', 'generic'.

    Returns:
        Parser instance with a `.parse(log: str)` method.
    """
    parser_cls = PARSERS.get(platform.lower(), GenericParser)
    return parser_cls()
