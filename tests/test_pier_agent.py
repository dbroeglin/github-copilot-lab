"""Tests for the local Pier Copilot CLI installed agent."""

from __future__ import annotations

import json
from pathlib import Path

from pier.models.agent.context import AgentContext

from copilot_experiments.pier_agents.copilot_cli import (
    COPILOT_CLI_AGENT_NAME,
    CopilotCli,
    find_copilot_otel_file,
)
from copilot_experiments.sessionlog import parse_metrics


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
    # Leading-dot wildcards cover the apex domain and all subdomains.
    assert {".github.com", ".githubcopilot.com", ".githubusercontent.com", "gh.io"} <= domains
    # Squid's dstdomain ACL fatals when a domain is listed both bare and as
    # ".domain"; guard against reintroducing such a conflict.
    bare = {d for d in domains if not d.startswith(".")}
    assert not any(f".{d}" in domains for d in bare), (
        "allowlist must not contain a domain both bare and as a .domain wildcard"
    )


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


def test_copilot_cli_configures_otel_file_export_by_default(tmp_path: Path):
    agent = CopilotCli(logs_dir=tmp_path)
    env: dict[str, str | None] = {}

    agent._configure_otel_env(env, "sess-1")

    assert env["COPILOT_OTEL_FILE_EXPORTER_PATH"] == "/logs/agent/copilot-otel.jsonl"
    assert env["COPILOT_OTEL_SOURCE_NAME"] == "copilot-experiments"
    assert env["OTEL_SERVICE_NAME"] == "copilot-experiments"
    assert "copilot.session_id=sess-1" in (env["OTEL_RESOURCE_ATTRIBUTES"] or "")
    assert "copilot.agent=copilot-cli" in (env["OTEL_RESOURCE_ATTRIBUTES"] or "")


def test_copilot_cli_preserves_explicit_otel_destination(tmp_path: Path):
    agent = CopilotCli(logs_dir=tmp_path)
    env: dict[str, str | None] = {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318"}

    agent._configure_otel_env(env, "sess-1")

    assert "COPILOT_OTEL_FILE_EXPORTER_PATH" not in env
    assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://collector:4318"
    assert "copilot.session_id=sess-1" in (env["OTEL_RESOURCE_ATTRIBUTES"] or "")


def test_copilot_cli_trajectory_includes_otel_llm_metrics(tmp_path: Path):
    agent = CopilotCli(logs_dir=tmp_path, model_name="claude-opus-4.8")
    jsonl_path = tmp_path / "copilot-cli.jsonl"
    events = _session_events()
    _write_jsonl(jsonl_path, events)
    otel_records = _otel_records()

    trajectory = agent._convert_to_trajectory(
        jsonl_path,
        events_path=None,
        parsed_metrics=parse_metrics(events),
        otel_records=otel_records,
    )

    assert trajectory is not None
    data = trajectory.to_json_dict()
    first_agent_step = data["steps"][1]
    second_agent_step = data["steps"][3]
    assert first_agent_step["metrics"]["prompt_tokens"] == 1000
    assert first_agent_step["metrics"]["completion_tokens"] == 100
    assert first_agent_step["llm_call_count"] == 1
    assert first_agent_step["metrics"]["extra"]["copilot_otel"] == {
        "llm_call_count": 1,
        "input_tokens": 1000,
        "cache_read_input_tokens": 700,
        "cache_creation_input_tokens": 200,
        "output_tokens": 100,
        "total_tokens": 1100,
        "aiu": 0.5,
        "server_duration_ms": 750,
        "current_tokens": 900,
        "token_limit": 2000,
        "llm_calls": [
            {
                "turn_id": "0",
                "started_at": "2026-01-01T00:00:01.100Z",
                "ended_at": "2026-01-01T00:00:01.900Z",
                "duration_s": 0.8,
                "request_model": "claude-opus-4.8",
                "response_model": "claude-opus-4.8",
                "finish_reasons": [],
                "input_tokens": 1000,
                "cache_read_input_tokens": 700,
                "cache_creation_input_tokens": 200,
                "output_tokens": 100,
                "total_tokens": 1100,
                "aiu": 0.5,
                "server_duration_ms": 750,
                "current_tokens": 900,
                "token_limit": 2000,
            }
        ],
    }
    assert second_agent_step["metrics"]["prompt_tokens"] == 1200
    assert second_agent_step["metrics"]["completion_tokens"] == 50

    final_otel = data["final_metrics"]["extra"]["copilot_otel"]
    assert final_otel == {
        "llm_call_count": 2,
        "input_tokens": 2200,
        "cache_read_input_tokens": 1600,
        "cache_creation_input_tokens": 250,
        "output_tokens": 150,
        "total_tokens": 2350,
        "aiu": 0.75,
        "server_duration_ms": 1200,
    }
    assert data["final_metrics"]["total_prompt_tokens"] == 2200
    assert data["final_metrics"]["total_completion_tokens"] == 150


def test_copilot_cli_trajectory_uses_otel_totals_without_shutdown_metrics(tmp_path: Path):
    agent = CopilotCli(logs_dir=tmp_path, model_name="claude-opus-4.8")
    jsonl_path = tmp_path / "copilot-cli.jsonl"
    events = _session_events(include_shutdown=False)
    _write_jsonl(jsonl_path, events)

    trajectory = agent._convert_to_trajectory(
        jsonl_path,
        events_path=None,
        parsed_metrics=parse_metrics(events),
        otel_records=_otel_records(),
    )

    assert trajectory is not None
    data = trajectory.to_json_dict()
    assert data["final_metrics"]["total_prompt_tokens"] == 2200
    assert data["final_metrics"]["total_completion_tokens"] == 150
    assert data["final_metrics"]["total_cached_tokens"] == 1600
    assert data["final_metrics"]["extra"]["copilot_otel"]["llm_call_count"] == 2


def test_copilot_cli_post_run_persists_trajectory_with_otel_file(tmp_path: Path):
    agent = CopilotCli(logs_dir=tmp_path, model_name="claude-opus-4.8")
    session_dir = tmp_path / "copilot-session" / "sess-1"
    session_dir.mkdir(parents=True)
    _write_jsonl(session_dir / "events.jsonl", _session_events())
    _write_jsonl(tmp_path / "copilot-cli.jsonl", [{"type": "message", "content": "fallback"}])
    _write_jsonl(tmp_path / "copilot-otel.jsonl", _otel_records())
    context = AgentContext()

    agent.populate_context_post_run(context)

    trajectory_path = tmp_path / "trajectory.json"
    assert trajectory_path.exists()
    data = json.loads(trajectory_path.read_text(encoding="utf-8"))
    first_agent_step = data["steps"][1]
    assert first_agent_step["message"] == "Looking at the code."
    assert first_agent_step["metrics"]["extra"]["copilot_otel"]["input_tokens"] == 1000
    assert data["final_metrics"]["extra"]["copilot_otel"]["llm_call_count"] == 2
    assert context.metadata["copilot_otel_file"] == "copilot-otel.jsonl"
    assert (
        context.metadata["copilot_session_events"].replace("\\", "/")
        == "copilot-session/sess-1/events.jsonl"
    )


def test_find_copilot_otel_file(tmp_path: Path):
    assert find_copilot_otel_file(tmp_path) is None
    otel_path = tmp_path / "copilot-otel.jsonl"
    otel_path.write_text("", encoding="utf-8")
    assert find_copilot_otel_file(tmp_path) == otel_path


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(record, separators=(",", ":")) for record in records) + "\n",
        encoding="utf-8",
    )


def _session_events(*, include_shutdown: bool = True) -> list[dict]:
    events = [
        {
            "type": "session.start",
            "timestamp": "2026-01-01T00:00:00.000Z",
            "data": {
                "sessionId": "sess-1",
                "selectedModel": "claude-opus-4.8",
            },
        },
        {
            "type": "user.message",
            "timestamp": "2026-01-01T00:00:01.000Z",
            "data": {"content": "Fix the bug"},
        },
        {
            "type": "assistant.turn_start",
            "timestamp": "2026-01-01T00:00:01.100Z",
            "data": {"turnId": "0"},
        },
        {
            "type": "assistant.message",
            "timestamp": "2026-01-01T00:00:01.500Z",
            "data": {
                "model": "claude-opus-4.8",
                "content": "Looking at the code.",
                "outputTokens": 100,
            },
        },
        {
            "type": "assistant.turn_end",
            "timestamp": "2026-01-01T00:00:02.000Z",
            "data": {"turnId": "0"},
        },
        {
            "type": "user.message",
            "timestamp": "2026-01-01T00:00:02.100Z",
            "data": {"content": "Now run tests"},
        },
        {
            "type": "assistant.turn_start",
            "timestamp": "2026-01-01T00:00:02.200Z",
            "data": {"turnId": "1"},
        },
        {
            "type": "assistant.message",
            "timestamp": "2026-01-01T00:00:02.500Z",
            "data": {
                "model": "claude-opus-4.8",
                "content": "Running tests.",
                "outputTokens": 50,
            },
        },
        {
            "type": "assistant.turn_end",
            "timestamp": "2026-01-01T00:00:03.000Z",
            "data": {"turnId": "1"},
        },
    ]
    if include_shutdown:
        events.append(
            {
                "type": "session.shutdown",
                "timestamp": "2026-01-01T00:00:03.100Z",
                "data": {
                    "durationMs": 3100,
                    "turns": 2,
                    "totalNanoAiu": 750_000_000,
                    "totalApiDurationMs": 1200,
                    "tokenDetails": {
                        "input": {"tokenCount": 1950},
                        "cache_read": {"tokenCount": 0},
                        "cache_write": {"tokenCount": 250},
                        "output": {"tokenCount": 150},
                    },
                },
            }
        )
    return events


def _otel_records() -> list[dict]:
    return [
        {
            "type": "span",
            "name": "chat claude-opus-4.8",
            "startTime": [1767225601, 100_000_000],
            "endTime": [1767225601, 900_000_000],
            "attributes": {
                "gen_ai.operation.name": "chat",
                "gen_ai.request.model": "claude-opus-4.8",
                "gen_ai.response.model": "claude-opus-4.8",
                "gen_ai.usage.input_tokens": 1000,
                "gen_ai.usage.cache_read_input_tokens": 700,
                "gen_ai.usage.cache_creation_input_tokens": 200,
                "gen_ai.usage.output_tokens": 100,
                "github.copilot.nano_aiu": 500_000_000,
                "github.copilot.server_duration": 750,
                "github.copilot.turn_id": "0",
            },
            "events": [
                {
                    "name": "github.copilot.session.usage_info",
                    "attributes": {
                        "github.copilot.current_tokens": 900,
                        "github.copilot.token_limit": 2000,
                    },
                }
            ],
        },
        {
            "type": "span",
            "name": "chat claude-opus-4.8",
            "startTime": [1767225602, 200_000_000],
            "endTime": [1767225602, 700_000_000],
            "attributes": {
                "gen_ai.operation.name": "chat",
                "gen_ai.request.model": "claude-opus-4.8",
                "gen_ai.response.model": "claude-opus-4.8",
                "gen_ai.usage.input_tokens": 1200,
                "gen_ai.usage.cache_read_input_tokens": 900,
                "gen_ai.usage.cache_creation_input_tokens": 50,
                "gen_ai.usage.output_tokens": 50,
                "github.copilot.nano_aiu": 250_000_000,
                "github.copilot.server_duration": 450,
                "github.copilot.turn_id": 1,
            },
        },
    ]
