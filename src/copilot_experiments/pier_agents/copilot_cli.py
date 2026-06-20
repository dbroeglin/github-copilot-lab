"""Pier installed agent that runs the real GitHub Copilot CLI."""

from __future__ import annotations

import json
import re
import shlex
import uuid
from pathlib import Path
from typing import Any

from pier.agents.installed.base import BaseInstalledAgent, CliFlag, with_prompt_template
from pier.environments.base import BaseEnvironment
from pier.models.agent.context import AgentContext
from pier.models.agent.install import AgentInstallSpec, InstallStep
from pier.models.agent.network import NetworkAllowlist
from pier.models.trajectories import (
    Agent,
    FinalMetrics,
    Metrics,
    Observation,
    ObservationResult,
    Step,
    ToolCall,
    Trajectory,
)
from pier.models.trial.paths import EnvironmentPaths
from pier.utils.trajectory_metrics import populate_context_from_final_metrics
from pier.utils.trajectory_utils import format_trajectory_json

from copilot_experiments.sessionlog import load_events, parse_metrics

COPILOT_CLI_AGENT_NAME = "copilot-cli"


class CopilotCli(BaseInstalledAgent):
    """Run GitHub Copilot CLI as-is inside a Pier-managed task environment."""

    SUPPORTS_ATIF = True

    _JSONL_FILENAME = "copilot-cli.jsonl"
    _OUTPUT_FILENAME = "copilot-cli.txt"
    _SESSION_ROOT = EnvironmentPaths.agent_dir / "copilot-session"
    _RE_VERSION = re.compile(r"(\d+\.\d+(?:\.\d+)?)")

    CLI_FLAGS = [
        CliFlag(
            "reasoning_effort",
            cli="--effort",
            type="enum",
            choices=["low", "medium", "high", "xhigh", "max"],
            env_fallback="COPILOT_CLI_EFFORT",
        ),
        CliFlag(
            "mode",
            cli="--mode",
            type="enum",
            choices=["plan", "interactive", "autopilot"],
            env_fallback="COPILOT_CLI_MODE",
        ),
        CliFlag(
            "context_tier",
            cli="--context-tier",
            type="enum",
            choices=["default", "long_context"],
            env_fallback="COPILOT_CLI_CONTEXT_TIER",
        ),
        CliFlag("agent", cli="--agent", type="str", env_fallback="COPILOT_CLI_AGENT"),
        CliFlag("allow_all_tools", cli="--allow-all-tools", type="bool", default=True),
    ]

    def __init__(
        self,
        *args: Any,
        command_model_name: str | None = None,
        extra_args: str | list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        self._command_model_name = command_model_name
        self._extra_args = extra_args
        super().__init__(*args, **kwargs)

    @staticmethod
    def name() -> str:
        return COPILOT_CLI_AGENT_NAME

    def get_version_command(self) -> str | None:
        return 'export PATH="$HOME/.local/bin:$PATH"; copilot --version'

    def parse_version(self, stdout: str) -> str:
        text = stdout.strip()
        match = self._RE_VERSION.search(text)
        return match.group(1) if match else text

    def network_allowlist(self) -> NetworkAllowlist:
        return NetworkAllowlist(
            domains=[
                "api.github.com",
                "github.com",
                ".github.com",
                "githubcopilot.com",
                ".githubcopilot.com",
                "githubusercontent.com",
                ".githubusercontent.com",
                "gh.io",
            ]
        )

    def install_spec(self) -> AgentInstallSpec:
        version_env = f" VERSION={shlex.quote(self._version)}" if self._version else ""
        root_run = (
            "if command -v apk >/dev/null 2>&1; then"
            "  apk add --no-cache bash ca-certificates curl git;"
            " elif command -v apt-get >/dev/null 2>&1; then"
            "  apt-get update && apt-get install -y bash ca-certificates curl git;"
            " elif command -v yum >/dev/null 2>&1; then"
            "  yum install -y ca-certificates curl git;"
            " else"
            "  echo 'Warning: no known package manager found' >&2;"
            " fi"
        )
        agent_run = (
            "set -euo pipefail; "
            f"curl -fsSL https://gh.io/copilot-install |{version_env} bash && "
            'export PATH="$HOME/.local/bin:$PATH" && '
            "copilot --version"
        )
        symlink_run = (
            "BIN_PATH=$(command -v copilot 2>/dev/null || true); "
            'if [ -n "$BIN_PATH" ] && [ "$BIN_PATH" != "/usr/local/bin/copilot" ]; then '
            'ln -sf "$BIN_PATH" /usr/local/bin/copilot; '
            "fi"
        )
        return AgentInstallSpec(
            agent_name=self.name(),
            version=self._version,
            steps=[
                InstallStep(user="root", env={"DEBIAN_FRONTEND": "noninteractive"}, run=root_run),
                InstallStep(user="agent", run=agent_run),
                InstallStep(user="root", run=symlink_run),
            ],
            verification_command='export PATH="$HOME/.local/bin:$PATH"; copilot --version',
        )

    def _extra_args_string(self) -> str:
        if self._extra_args is None:
            return ""
        if isinstance(self._extra_args, str):
            return self._extra_args.strip()
        return shlex.join([str(arg) for arg in self._extra_args])

    def _build_mcp_config_flag(self) -> str:
        if not self.mcp_servers:
            return ""
        servers: dict[str, dict[str, Any]] = {}
        for server in self.mcp_servers:
            if server.transport == "stdio":
                servers[server.name] = {
                    "type": "stdio",
                    "command": server.command,
                    "args": server.args,
                }
            else:
                servers[server.name] = {"type": server.transport, "url": server.url}
        config = json.dumps({"mcpServers": servers}, separators=(",", ":"))
        return f"--additional-mcp-config={shlex.quote(config)}"

    def _build_register_skills_command(self) -> str:
        if not self.skills_dir:
            return ""
        return (
            "mkdir -p ~/.copilot && "
            f"cp -r {shlex.quote(self.skills_dir)}/* ~/.copilot/ 2>/dev/null || true"
        )

    def _copilot_auth_env(self) -> dict[str, str | None]:
        token = (
            self._get_env("COPILOT_GITHUB_TOKEN")
            or self._get_env("GITHUB_TOKEN")
            or self._get_env("GH_TOKEN")
        )
        return {
            "COPILOT_GITHUB_TOKEN": token,
            "GITHUB_TOKEN": token,
            "GH_TOKEN": token,
        }

    @with_prompt_template
    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        session_id = str(uuid.uuid4())
        model = self._command_model_name or (
            self.model_name.split("/")[-1] if self.model_name else None
        )

        flags = [self.build_cli_flags()]
        if model:
            flags.append(f"--model {shlex.quote(model)}")
        flags.append(f"--session-id {shlex.quote(session_id)}")
        flags.append(f"--log-dir {shlex.quote(self._SESSION_ROOT.as_posix())}")
        mcp_flag = self._build_mcp_config_flag()
        if mcp_flag:
            flags.append(mcp_flag)
        extra_args = self._extra_args_string()
        if extra_args:
            flags.append(extra_args)
        flag_text = " ".join(flag for flag in flags if flag)

        env = self.build_process_env(self._copilot_auth_env())
        agent_dir = EnvironmentPaths.agent_dir.as_posix()
        session_root = self._SESSION_ROOT.as_posix()
        jsonl_path = (EnvironmentPaths.agent_dir / self._JSONL_FILENAME).as_posix()
        output_path = (EnvironmentPaths.agent_dir / self._OUTPUT_FILENAME).as_posix()

        setup_commands = [
            f"mkdir -p {shlex.quote(agent_dir)} {shlex.quote(session_root)}",
            'export PATH="$HOME/.local/bin:$PATH"',
        ]
        skills_command = self._build_register_skills_command()
        if skills_command:
            setup_commands.append(skills_command)
        setup = " && ".join(setup_commands)

        command = self._build_run_command(
            setup=setup,
            instruction=instruction,
            flag_text=flag_text,
            session_id=session_id,
            session_root=session_root,
            jsonl_path=jsonl_path,
            output_path=output_path,
        )
        await self.exec_as_agent(environment, command=command, env=env)

    def _build_run_command(
        self,
        *,
        setup: str,
        instruction: str,
        flag_text: str,
        session_id: str,
        session_root: str,
        jsonl_path: str,
        output_path: str,
    ) -> str:
        escaped_instruction = shlex.quote(instruction)
        run_script = (
            'export PATH="$HOME/.local/bin:$PATH"; '
            "set -o pipefail; "
            f"copilot -p {escaped_instruction} --output-format json {flag_text} "
            f"2>&1 | tee {shlex.quote(jsonl_path)} > {shlex.quote(output_path)}; "
            "status=${PIPESTATUS[0]}; "
            f'session_state="$HOME/.copilot/session-state/{session_id}"; '
            f'if [ -d "$session_state" ]; then cp -a "$session_state" '
            f"{shlex.quote(session_root)}; "
            'else echo "Copilot session state not found: $session_state" >&2; fi; '
            "exit $status"
        )
        return f"{setup} && bash -lc {shlex.quote(run_script)}"

    def populate_context_post_run(self, context: AgentContext) -> None:
        """Convert captured Copilot logs to ATIF and Pier context metrics."""

        events_path = find_copilot_session_events(self.logs_dir)
        metrics = None
        if events_path is not None:
            try:
                metrics = parse_metrics(load_events(events_path))
            except Exception:
                self.logger.exception("Failed to parse Copilot session events from %s", events_path)

        jsonl_path = self.logs_dir / self._JSONL_FILENAME
        trajectory = None
        try:
            trajectory = self._convert_to_trajectory(jsonl_path, events_path, metrics)
        except Exception:
            self.logger.exception("Failed to convert Copilot CLI logs to ATIF")

        if trajectory is not None:
            trajectory_path = self.logs_dir / "trajectory.json"
            trajectory_path.write_text(
                format_trajectory_json(trajectory.to_json_dict()),
                encoding="utf-8",
            )
            if trajectory.final_metrics is not None:
                populate_context_from_final_metrics(context, trajectory.final_metrics)

        if metrics is not None:
            context.n_input_tokens = metrics.input_tokens
            context.n_cache_tokens = metrics.cache_read_tokens
            context.n_output_tokens = metrics.output_tokens
            context.peak_context_tokens = metrics.peak_context_tokens
            context.summarization_count = metrics.n_compactions
            context.n_agent_steps = metrics.n_turns
            context.metadata = {
                **(context.metadata or {}),
                "copilot_session_events": str(events_path.relative_to(self.logs_dir)),
                "copilot_aiu": metrics.aiu,
            }

    def _convert_to_trajectory(
        self,
        jsonl_path: Path,
        events_path: Path | None,
        parsed_metrics: Any,
    ) -> Trajectory | None:
        raw_events = _read_jsonl(jsonl_path)
        if not raw_events and events_path is not None:
            raw_events = load_events(events_path)
        if not raw_events:
            return None

        steps: list[Step] = []
        call_owners: dict[str, Step] = {}

        def append_step(step: Step) -> None:
            step.step_id = len(steps) + 1
            steps.append(step)

        for event in raw_events:
            if not isinstance(event, dict):
                continue
            event_type = event.get("type")
            timestamp = event.get("timestamp")

            if event_type == "user.message":
                data = event.get("data") or {}
                message = _flatten_content(data.get("content"))
                if message:
                    append_step(
                        Step(step_id=1, timestamp=timestamp, source="user", message=message)
                    )
                continue

            if event_type == "assistant.message":
                data = event.get("data") or {}
                tool_calls = [
                    ToolCall(
                        tool_call_id=str(request.get("toolCallId") or ""),
                        function_name=str(request.get("name") or ""),
                        arguments=_normalize_arguments(request.get("arguments")),
                    )
                    for request in data.get("toolRequests") or []
                ]
                output_tokens = data.get("outputTokens") or None
                step = Step(
                    step_id=1,
                    timestamp=timestamp,
                    source="agent",
                    message=_flatten_content(data.get("content")) or "Tool call",
                    model_name=data.get("model") or self.model_name,
                    tool_calls=tool_calls or None,
                    metrics=Metrics(completion_tokens=output_tokens) if output_tokens else None,
                )
                append_step(step)
                for tool_call in tool_calls:
                    if tool_call.tool_call_id:
                        call_owners[tool_call.tool_call_id] = step
                continue

            if event_type == "tool.execution_complete":
                data = event.get("data") or {}
                call_id = data.get("toolCallId")
                content = _stringify_tool_result(data.get("result"))
                if data.get("error") is not None:
                    error = _stringify_tool_result(data.get("error"))
                    content = error if not content else f"{content}\n{error}"
                _attach_observation(call_owners, steps, call_id, content, timestamp)
                continue

            if event_type == "message":
                role = event.get("role", "user")
                source = "agent" if role == "assistant" else "user"
                kwargs: dict[str, Any] = {}
                if source == "agent":
                    kwargs["model_name"] = event.get("model") or self.model_name
                append_step(
                    Step(
                        step_id=1,
                        timestamp=timestamp,
                        source=source,
                        message=_flatten_content(event.get("content")),
                        **kwargs,
                    )
                )
                continue

            if event_type == "tool_use":
                call_id = str(event.get("id") or "")
                step = Step(
                    step_id=1,
                    timestamp=timestamp,
                    source="agent",
                    message=f"Executed {event.get('name') or 'tool'}",
                    model_name=event.get("model") or self.model_name,
                    tool_calls=[
                        ToolCall(
                            tool_call_id=call_id,
                            function_name=str(event.get("name") or ""),
                            arguments=_normalize_arguments(event.get("input")),
                        )
                    ],
                )
                append_step(step)
                if call_id:
                    call_owners[call_id] = step
                continue

            if event_type == "tool_result":
                _attach_observation(
                    call_owners,
                    steps,
                    event.get("tool_use_id"),
                    _flatten_content(event.get("content")),
                    timestamp,
                )

        if not steps:
            return None

        final_metrics = None
        if parsed_metrics is not None:
            final_metrics = FinalMetrics(
                total_prompt_tokens=parsed_metrics.input_tokens,
                total_completion_tokens=parsed_metrics.output_tokens,
                total_cached_tokens=parsed_metrics.cache_read_tokens,
                total_steps=len(steps),
                extra={
                    key: value
                    for key, value in {
                        "total_tokens": parsed_metrics.total_tokens,
                        "aiu": parsed_metrics.aiu,
                        "reasoning_tokens": parsed_metrics.reasoning_tokens,
                        "peak_context_tokens": parsed_metrics.peak_context_tokens,
                        "summarization_count": parsed_metrics.n_compactions,
                    }.items()
                    if value is not None
                }
                or None,
            )

        return Trajectory(
            schema_version="ATIF-v1.7",
            session_id=str(_first_event_session_id(raw_events) or "copilot-cli"),
            agent=Agent(
                name=self.name(),
                version=self.version() or "unknown",
                model_name=self.model_name,
            ),
            steps=steps,
            final_metrics=final_metrics,
        )


def find_copilot_session_events(agent_logs_dir: Path) -> Path | None:
    """Find the native Copilot ``events.jsonl`` captured by this Pier agent."""

    candidates = sorted(
        (agent_logs_dir / "copilot-session").glob("**/events.jsonl"),
        key=lambda path: path.stat().st_mtime,
    )
    return candidates[-1] if candidates else None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _flatten_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(_flatten_content(part) for part in content)
    if isinstance(content, dict):
        if isinstance(content.get("text"), str):
            return content["text"]
        if isinstance(content.get("content"), str):
            return content["content"]
    return str(content)


def _normalize_arguments(arguments: Any) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    if arguments is None:
        return {}
    return {"value": arguments}


def _stringify_tool_result(result: Any) -> str:
    if isinstance(result, dict):
        for key in ("content", "output", "stdout", "text", "message"):
            value = result.get(key)
            if isinstance(value, str):
                remainder = {k: v for k, v in result.items() if k != key}
                if remainder:
                    return f"{value}\n{json.dumps(remainder, ensure_ascii=False)}"
                return value
        return json.dumps(result, ensure_ascii=False)
    return _flatten_content(result)


def _attach_observation(
    call_owners: dict[str, Step],
    steps: list[Step],
    call_id: Any,
    content: str,
    timestamp: str | None,
) -> None:
    call_id_text = str(call_id or "")
    owner = call_owners.get(call_id_text) if call_id_text else None
    if owner is None:
        steps.append(
            Step(
                step_id=len(steps) + 1,
                timestamp=timestamp,
                source="agent",
                message=content or "Tool result",
                extra={"source_call_id": call_id_text} if call_id_text else None,
            )
        )
        return

    result = ObservationResult(source_call_id=call_id_text, content=content or None)
    if owner.observation is None:
        owner.observation = Observation(results=[result])
    else:
        owner.observation.results.append(result)


def _first_event_session_id(events: list[dict[str, Any]]) -> str | None:
    for event in events:
        if event.get("type") == "session.start":
            data = event.get("data") or {}
            value = data.get("sessionId") or data.get("session_id")
            return str(value) if value else None
    return None
