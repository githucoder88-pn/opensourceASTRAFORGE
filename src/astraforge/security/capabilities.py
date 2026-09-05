"""Capability names that tools must declare and policies must grant."""

from __future__ import annotations

from enum import Enum


class Capability(str, Enum):
    """Fine-grained permission required to execute a tool.

    A tool declares the capabilities it needs; the active
    :class:`~astraforge.policies.policy.Policy` decides whether they are
    granted, require human approval, or are denied outright.
    """

    FILESYSTEM_READ = "filesystem.read"
    FILESYSTEM_WRITE = "filesystem.write"
    SHELL_EXECUTE = "shell.execute"
    NETWORK_REQUEST = "network.request"
    GITHUB_READ = "github.read"
    GITHUB_WRITE = "github.write"
    BROWSER_READ = "browser.read"
    BROWSER_INTERACT = "browser.interact"
    MODEL_INVOKE = "model.invoke"
