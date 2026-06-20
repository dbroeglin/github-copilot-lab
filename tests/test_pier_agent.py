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


def test_copilot_cli_run_command_copies_native_session_state(tmp_path: Path):
    agent = CopilotCli(logs_dir=tmp_path)

    command = agent._build_run_command(
        setup="mkdir -p /logs/agent /logs/agent/copilot-session",
        instruction="fix it",
        flag_text="--session-id 1234 --log-dir /logs/agent/copilot-session",
        session_id="1234",
        session_root="/logs/agent/copilot-session",
        jsonl_path="/logs/agent/copilot-cli.jsonl",
        output_path="/logs/agent/copilot-cli.txt",
    )

    assert "bash -lc" in command
    assert "set -o pipefail" in command
    assert "status=${PIPESTATUS[0]}" in command
    assert 'session_state="$HOME/.copilot/session-state/1234"' in command
    assert 'cp -a "$session_state" /logs/agent/copilot-session' in command
    assert "exit $status" in command
