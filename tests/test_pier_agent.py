"""Tests for the local Pier Copilot CLI installed agent."""

from __future__ import annotations

from pathlib import Path

from copilot_experiments.pier_agents.copilot_cli import COPILOT_CLI_AGENT_NAME, CopilotCli


def test_copilot_cli_agent_metadata(tmp_path: Path):
    agent = CopilotCli(
        logs_dir=tmp_path,
        model_name="gpt-5-mini",
        reasoning_effort="low",
        extra_args=["--foo", "bar baz"],
    )

    assert agent.name() == COPILOT_CLI_AGENT_NAME
    assert agent.import_path() == "copilot_experiments.pier_agents.copilot_cli:CopilotCli"
    assert "--effort low" in agent.build_cli_flags()
    assert "--allow-all-tools" in agent.build_cli_flags()
    assert agent._extra_args_string() == "--foo 'bar baz'"


def test_copilot_cli_install_spec_and_allowlist(tmp_path: Path):
    agent = CopilotCli(logs_dir=tmp_path, version="1.0.64")

    install = agent.install_spec()
    domains = set(agent.network_allowlist().domains)

    assert install.agent_name == "copilot-cli"
    assert install.version == "1.0.64"
    assert any("https://gh.io/copilot-install" in step.run for step in install.steps)
    assert install.verification_command and "copilot --version" in install.verification_command
    assert {"github.com", "api.github.com", "githubcopilot.com", "gh.io"} <= domains


def test_copilot_cli_version_parser(tmp_path: Path):
    agent = CopilotCli(logs_dir=tmp_path)

    assert agent.parse_version("GitHub Copilot CLI 1.0.64-0\n") == "1.0.64"
    assert agent.parse_version("dev-build") == "dev-build"
