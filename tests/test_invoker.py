"""MockInvoker and argument/env translation tests.

Proves the mock actually mutates the workspace and emits a parseable, multi-turn
session log, and that a variant is translated into the right ``copilot`` flags
and environment (including BYOK secrets that must never reach stored artifacts).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from copilot_experiments.invoker import (
    CopilotInvoker,
    Invocation,
    MockInvoker,
    build_args,
    build_env,
)
from copilot_experiments.models import ProviderConfig, Variant
from copilot_experiments.sessionlog import events_path, load_events, parse_metrics


def _inv(tmp_path: Path, variant: Variant, *, session_id: str = "sess-1") -> Invocation:
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    return Invocation(
        prompt="do the thing",
        workspace=ws,
        session_id=session_id,
        variant=variant,
        log_dir=tmp_path / "logs",
        stdout_path=tmp_path / "stdout.jsonl",
        session_state_root=tmp_path / "state",
    )


def test_mock_solver_mutates_workspace(tmp_path: Path):
    seen: dict[str, Path] = {}

    def solver(ws: Path) -> None:
        seen["ws"] = ws
        (ws / "SOLVED").write_text("yes\n", encoding="utf-8")

    inv = _inv(tmp_path, Variant(name="v"))
    MockInvoker(solver=solver).run(inv)

    assert (inv.workspace / "SOLVED").read_text(encoding="utf-8") == "yes\n"
    assert seen["ws"] == inv.workspace
    # With a solver, the default note is not written.
    assert not (inv.workspace / "MOCK_RUN.md").exists()


def test_mock_leaves_note_by_default(tmp_path: Path):
    inv = _inv(tmp_path, Variant(name="v"))
    MockInvoker().run(inv)
    assert (inv.workspace / "MOCK_RUN.md").exists()


def test_mock_writes_parseable_multiturn_log(tmp_path: Path):
    inv = _inv(tmp_path, Variant(name="v", reasoning_effort="high"))
    result = MockInvoker(turns=4).run(inv)
    assert result.exit_code == 0

    ev_path = events_path(inv.session_id, inv.session_state_root)
    assert ev_path.exists()
    # The same stream is also mirrored to stdout for the trial record.
    assert inv.stdout_path.exists()

    metrics = parse_metrics(load_events(ev_path))
    assert metrics.n_turns >= 4
    assert metrics.n_tool_calls >= 1
    assert metrics.n_tool_failures >= 1  # the deliberate powershell failure + recovery
    assert metrics.output_tokens and metrics.output_tokens > 0


def test_mock_nonzero_exit_is_reported(tmp_path: Path):
    inv = _inv(tmp_path, Variant(name="v"))
    result = MockInvoker(exit_code=2).run(inv)
    assert result.exit_code == 2


def test_build_args_translates_variant_flags():
    variant = Variant(
        name="v",
        model="gpt-x",
        reasoning_effort="high",
        agent="my-agent",
        mode="autopilot",
        allow_tools=["shell"],
        deny_tools=["web"],
    )
    inv = Invocation(
        prompt="P",
        workspace=Path("."),
        session_id="s",
        variant=variant,
        log_dir=Path("l"),
        stdout_path=Path("o"),
        session_state_root=Path("st"),
    )
    args = build_args(inv)

    assert args[:2] == ["-p", "P"]
    for flag, value in [
        ("--model", "gpt-x"),
        ("--effort", "high"),
        ("--agent", "my-agent"),
        ("--mode", "autopilot"),
    ]:
        assert flag in args
        assert args[args.index(flag) + 1] == value
    assert "--allow-all-tools" in args  # default
    assert args.count("--allow-tool") == 1
    assert args.count("--deny-tool") == 1


def test_build_args_emits_share_and_secret_env_vars(tmp_path: Path):
    inv = Invocation(
        prompt="P",
        workspace=tmp_path / "ws",
        session_id="s",
        variant=Variant(name="v"),
        log_dir=tmp_path / "logs",
        stdout_path=tmp_path / "stdout.txt",
        session_state_root=tmp_path / "state",
        share_path=tmp_path / "session.md",
        secret_env_names=["COPILOT_GITHUB_TOKEN", "GH_TOKEN"],
    )
    args = build_args(inv)

    share = next(a for a in args if a.startswith("--share="))
    assert Path(share.split("=", 1)[1]) == (tmp_path / "session.md").resolve()

    secret = next(a for a in args if a.startswith("--secret-env-vars="))
    assert secret.split("=", 1)[1] == "COPILOT_GITHUB_TOKEN,GH_TOKEN"


def test_build_args_omits_share_and_secrets_when_unset(tmp_path: Path):
    inv = Invocation(
        prompt="P",
        workspace=tmp_path / "ws",
        session_id="s",
        variant=Variant(name="v"),
        log_dir=tmp_path / "logs",
        stdout_path=tmp_path / "stdout.txt",
        session_state_root=tmp_path / "state",
    )
    args = build_args(inv)
    assert not any(a.startswith("--share") for a in args)
    assert not any(a.startswith("--secret-env-vars") for a in args)


def test_build_args_uses_absolute_workspace_and_log_dir(tmp_path: Path):
    # Regression: a *relative* ``-C`` was resolved against the process cwd (already
    # the workspace) and doubled -> ENAMETOOLONG -> Copilot no-op. ``-C`` and
    # ``--log-dir`` must always be absolute. See ADR-0009.
    ws = tmp_path / "ws"
    ws.mkdir()
    inv = Invocation(
        prompt="P",
        workspace=Path("ws"),  # deliberately relative
        session_id="s",
        variant=Variant(name="v"),
        log_dir=Path("logs"),  # deliberately relative
        stdout_path=tmp_path / "stdout.jsonl",
        session_state_root=tmp_path / "state",
    )
    args = build_args(inv)

    c_path = Path(args[args.index("-C") + 1])
    log_path = Path(args[args.index("--log-dir") + 1])
    assert c_path.is_absolute()
    assert log_path.is_absolute()
    assert c_path == Path("ws").resolve()
    assert log_path == Path("logs").resolve()


def test_streaming_invoker_tees_lines_to_sink_and_file(tmp_path: Path):
    # ``--verbose`` relies on the streaming path forwarding every Copilot output
    # line to the sink *and* still capturing it to stdout.jsonl. Drive it with a
    # trivial Python subprocess so the test stays offline and cross-platform.
    collected: list[str] = []
    invoker = CopilotInvoker(binary=sys.executable, stream=collected.append)
    stdout_path = tmp_path / "stdout.jsonl"
    script = "import sys\nfor i in range(3): print('line', i)\nsys.exit(0)\n"
    code = invoker._run_streaming(
        [sys.executable, "-c", script], str(tmp_path), dict(os.environ), stdout_path
    )

    assert code == 0
    assert collected == ["line 0", "line 1", "line 2"]
    captured = stdout_path.read_text(encoding="utf-8").splitlines()
    assert captured == ["line 0", "line 1", "line 2"]


def test_build_env_injects_provider_but_storage_redacts():
    provider = ProviderConfig(base_url="http://localhost:11434/v1", api_key="SECRET-KEY")
    variant = Variant(name="v", provider=provider, env={"FOO": "bar"})
    inv = Invocation(
        prompt="P",
        workspace=Path("."),
        session_id="s",
        variant=variant,
        log_dir=Path("l"),
        stdout_path=Path("o"),
        session_state_root=Path("st"),
    )

    env = build_env(inv)
    assert env["FOO"] == "bar"
    assert env["COPILOT_PROVIDER_API_KEY"] == "SECRET-KEY"

    # The secret must never appear in what gets written to disk.
    assert "SECRET-KEY" not in str(variant.stored())
