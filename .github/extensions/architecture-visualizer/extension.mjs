import { createServer } from "node:http";
import { createCanvas, CanvasError, joinSession } from "@github/copilot-sdk/extension";
import { layoutLayeredGraph } from "./graph-layout.mjs";

const COMPONENT_IDS = [
    "task-authoring",
    "deepswe-import",
    "scaffold-template",
    "typer-cli",
    "pier-backend",
    "pier-job",
    "pier-environment",
    "pier-verifier",
    "copilot-installed-agent",
    "real-copilot-cli",
    "native-session-logs",
    "otel-atif",
    "job-artifacts",
    "session-analysis",
    "summary-reporting",
    "derived-index",
    "legacy-runner",
];

const ARCHITECTURE = {
    name: "copilot-experiments",
    tagline:
        "A Pier-first experiment harness for running GitHub Copilot CLI in sandboxed coding tasks and analyzing native Copilot session output.",
    invariants: [
        "Pier jobs are canonical for new runs.",
        "Copilot CLI remains the system under test; the package shells out to the real binary.",
        "Native Copilot events.jsonl logs are primary for Copilot-specific metrics.",
        "SQLite indexes are derived caches and can be rebuilt from artifacts.",
        "Tests stay offline by using fixtures, config parsing, and mock invokers.",
        "Secrets are injected at run time and kept out of persisted result config.",
    ],
    layers: [
        {
            id: "authoring",
            name: "Experiment authoring",
            summary: "Tasks, imported corpora, and scaffolded repos define what to run.",
        },
        {
            id: "interface",
            name: "CLI and adapters",
            summary: "Typer commands normalize input, scaffold repos, and call Pier.",
        },
        {
            id: "execution",
            name: "Pier execution",
            summary: "Pier owns jobs, sandboxes, trial orchestration, and verification.",
        },
        {
            id: "agent",
            name: "Copilot agent",
            summary: "The installed Pier agent invokes the real GitHub Copilot CLI.",
        },
        {
            id: "capture",
            name: "Telemetry capture",
            summary: "Native session logs, OTel, ATIF, and trial artifacts are persisted.",
        },
        {
            id: "analysis",
            name: "Analysis and reporting",
            summary: "Session metrics, summaries, terminal rendering, and indexes are derived.",
        },
    ],
    nodes: [
        {
            id: "task-authoring",
            layer: "authoring",
            title: "Harbor/Pier task directories",
            subtitle: "task.toml, instruction.md, environment/, tests/",
            x: 40,
            y: 80,
            files: ["tasks/<id>/", "experiments/*.yaml", "docs/authoring-experiments.md"],
            details:
                "Experiment authors describe tasks and Pier JobConfig YAML. Each task carries the instruction, environment, verifier tests, and optional solution artifacts.",
        },
        {
            id: "deepswe-import",
            layer: "authoring",
            title: "DeepSWE import",
            subtitle: "Generate Pier jobs from large task corpora",
            x: 40,
            y: 210,
            files: ["src/copilot_experiments/deepswe.py", "docs/deepswe.md"],
            details:
                "The import command converts DeepSWE-style inputs into Pier task/job structure so large benchmark protocols can use the same execution path.",
        },
        {
            id: "scaffold-template",
            layer: "authoring",
            title: "Experiment repo template",
            subtitle: "Standalone repo bootstrap",
            x: 40,
            y: 340,
            files: [
                "src/copilot_experiments/scaffold.py",
                "src/copilot_experiments/templates/experiment_repo/",
            ],
            details:
                "The init command renders package-data templates into a separate experiment repository with example task, job config, APM context, and docs.",
        },
        {
            id: "typer-cli",
            layer: "interface",
            title: "Typer CLI",
            subtitle: "init, run, list, show, inspect, analyze, reindex",
            x: 270,
            y: 80,
            files: ["src/copilot_experiments/cli.py", "README.md"],
            details:
                "The console entry point exposes the library as copilot-experiments. Commands dispatch to Pier-first paths and keep legacy behavior available when no Pier configs exist.",
        },
        {
            id: "pier-backend",
            layer: "interface",
            title: "Pier backend adapter",
            subtitle: "Normalize JobConfig and inject runtime auth",
            x: 270,
            y: 240,
            files: ["src/copilot_experiments/pier_backend.py"],
            details:
                "This adapter discovers Pier YAML/JSON configs, maps name: copilot-cli to the local installed-agent import path, redacts persisted secrets, and calls Pier's Python API.",
        },
        {
            id: "pier-job",
            layer: "execution",
            title: "pier.job.Job",
            subtitle: "Trial orchestration and artifact transfer",
            x: 500,
            y: 80,
            files: ["jobs/<job>/", "docs/results-format.md"],
            details:
                "Pier is the execution substrate. It creates job/trial directories, launches environments, runs installed agents, executes verifiers, and copies artifacts out.",
        },
        {
            id: "pier-environment",
            layer: "execution",
            title: "Pier environment",
            subtitle: "Docker, Modal, Daytona",
            x: 500,
            y: 210,
            files: ["tasks/<id>/environment/", "tests/test_pier_backend.py"],
            details:
                "Task environments provide the sandbox where the agent edits code and tests run. The harness delegates backend-specific isolation to Pier.",
        },
        {
            id: "pier-verifier",
            layer: "execution",
            title: "Pier verifier",
            subtitle: "tests/test.sh -> reward.txt or reward.json",
            x: 500,
            y: 340,
            files: ["tasks/<id>/tests/test.sh", "tests/test_pier_results.py"],
            details:
                "After an agent attempt, Pier runs task tests and writes reward signals. Reporting adapts those results into show/inspect summaries.",
        },
        {
            id: "copilot-installed-agent",
            layer: "agent",
            title: "Copilot CLI installed agent",
            subtitle: "Pier BaseInstalledAgent wrapper",
            x: 730,
            y: 80,
            files: ["src/copilot_experiments/pier_agents/copilot_cli.py"],
            details:
                "The local Pier agent installs or locates GitHub Copilot CLI, configures network allowlists and telemetry, passes model/effort/mode kwargs, and emits ATIF trajectory output.",
        },
        {
            id: "real-copilot-cli",
            layer: "agent",
            title: "Real GitHub Copilot CLI",
            subtitle: "copilot -p --output-format json --session-id --log-dir",
            x: 730,
            y: 240,
            files: ["src/copilot_experiments/invoker.py", "docs/collecting-run-data.md"],
            details:
                "Copilot itself is not reimplemented. Runs shell out to the actual CLI so sessions, tool calls, pricing events, and shutdown records match production behavior.",
        },
        {
            id: "native-session-logs",
            layer: "capture",
            title: "Native session logs",
            subtitle: "copilot-session/<id>/events.jsonl",
            x: 960,
            y: 80,
            files: ["src/copilot_experiments/sessionlog.py", "docs/analysis.md"],
            details:
                "The installed agent copies Copilot's session-state directory into Pier logs. sessionlog.py parses events.jsonl into metrics, including token and AIU economics.",
        },
        {
            id: "otel-atif",
            layer: "capture",
            title: "OTel + ATIF trajectory",
            subtitle: "Per-call telemetry and cross-agent trace",
            x: 960,
            y: 210,
            files: [
                "docs/collecting-run-data.md",
                "src/copilot_experiments/pier_agents/copilot_cli.py",
            ],
            details:
                "When no explicit OTLP destination is configured, Copilot OTel data is written to a local JSONL file. ATIF remains available for cross-agent compatibility and fallback metrics.",
        },
        {
            id: "job-artifacts",
            layer: "capture",
            title: "Pier job artifacts",
            subtitle: "jobs/<job>/<trial>/",
            x: 960,
            y: 340,
            files: ["jobs/<job>/", "src/copilot_experiments/storage.py"],
            details:
                "Trial directories store verifier output, Copilot logs, trajectories, raw CLI output, and run metadata. storage.py locates canonical jobs plus legacy results.",
        },
        {
            id: "session-analysis",
            layer: "analysis",
            title: "Session analysis",
            subtitle: "Tools, turns, tokens, AIU economics",
            x: 1190,
            y: 80,
            files: [
                "src/copilot_experiments/analysis.py",
                "src/copilot_experiments/render.py",
                "src/copilot_experiments/pricing.py",
            ],
            details:
                "analysis.py builds rendering-agnostic session views, pricing.py decomposes token economics, and render.py presents the rich terminal analyze command.",
        },
        {
            id: "summary-reporting",
            layer: "analysis",
            title: "Summary and inspection",
            subtitle: "summary.json, summary.md, show, inspect",
            x: 1190,
            y: 240,
            files: ["src/copilot_experiments/pier_results.py", "src/copilot_experiments/report.py"],
            details:
                "Pier job directories are adapted into the existing result shape and aggregated into human-readable and machine-readable summaries.",
        },
        {
            id: "derived-index",
            layer: "analysis",
            title: "Derived SQLite index",
            subtitle: "results/index.db rebuilt from disk",
            x: 1190,
            y: 390,
            files: ["src/copilot_experiments/index.py", "src/copilot_experiments/storage.py"],
            details:
                "The index is a rebuildable cache over canonical jobs and legacy results. reindex always reconstructs it from filesystem artifacts.",
        },
        {
            id: "legacy-runner",
            layer: "execution",
            title: "Legacy compatibility path",
            subtitle: "Experiment x Variant x Task x Trial",
            x: 500,
            y: 510,
            files: [
                "src/copilot_experiments/models.py",
                "src/copilot_experiments/runner.py",
                "src/copilot_experiments/workspace.py",
                "src/copilot_experiments/invoker.py",
            ],
            details:
                "When no Pier JobConfig exists, the original Python runner remains available. It provisions workspaces, invokes Copilot or MockInvoker, captures diffs, and writes legacy results.",
        },
    ],
    edges: [
        {
            from: "task-authoring",
            to: "typer-cli",
            label: "run/show/analyze commands",
            kind: "control",
        },
        {
            from: "deepswe-import",
            to: "typer-cli",
            label: "deepswe-import",
            kind: "control",
        },
        {
            from: "scaffold-template",
            to: "task-authoring",
            label: "init creates",
            kind: "artifact",
        },
        {
            from: "typer-cli",
            to: "pier-backend",
            label: "Pier config discovery",
            kind: "control",
        },
        {
            from: "pier-backend",
            to: "pier-job",
            label: "normalized JobConfig",
            kind: "control",
        },
        {
            from: "pier-job",
            to: "pier-environment",
            label: "launch sandbox",
            kind: "control",
        },
        {
            from: "pier-job",
            to: "copilot-installed-agent",
            label: "run agent",
            kind: "control",
        },
        {
            from: "copilot-installed-agent",
            to: "real-copilot-cli",
            label: "shell out",
            kind: "control",
        },
        {
            from: "real-copilot-cli",
            to: "native-session-logs",
            label: "events.jsonl",
            kind: "telemetry",
        },
        {
            from: "real-copilot-cli",
            to: "otel-atif",
            label: "raw output + OTel",
            kind: "telemetry",
        },
        {
            from: "copilot-installed-agent",
            to: "otel-atif",
            label: "trajectory.json",
            kind: "telemetry",
        },
        {
            from: "pier-job",
            to: "pier-verifier",
            label: "verify trial",
            kind: "control",
        },
        {
            from: "pier-verifier",
            to: "job-artifacts",
            label: "reward output",
            kind: "artifact",
        },
        {
            from: "native-session-logs",
            to: "job-artifacts",
            label: "persisted logs",
            kind: "artifact",
        },
        {
            from: "otel-atif",
            to: "job-artifacts",
            label: "persisted traces",
            kind: "artifact",
        },
        {
            from: "job-artifacts",
            to: "session-analysis",
            label: "events + OTel",
            kind: "analysis",
        },
        {
            from: "native-session-logs",
            to: "session-analysis",
            label: "primary metrics",
            kind: "analysis",
        },
        {
            from: "job-artifacts",
            to: "summary-reporting",
            label: "trial status",
            kind: "analysis",
        },
        {
            from: "session-analysis",
            to: "summary-reporting",
            label: "analyze view",
            kind: "analysis",
        },
        {
            from: "job-artifacts",
            to: "derived-index",
            label: "reindex scan",
            kind: "analysis",
        },
        {
            from: "legacy-runner",
            to: "job-artifacts",
            label: "legacy results",
            kind: "artifact",
        },
        {
            from: "legacy-runner",
            to: "summary-reporting",
            label: "compat summaries",
            kind: "analysis",
        },
        {
            from: "legacy-runner",
            to: "derived-index",
            label: "legacy scan",
            kind: "analysis",
        },
    ],
};

const LAID_OUT_ARCHITECTURE = layoutLayeredGraph(ARCHITECTURE);

const servers = new Map();

const openInputSchema = {
    type: "object",
    additionalProperties: false,
    properties: {
        focus: {
            type: "string",
            enum: COMPONENT_IDS,
            description: "Optional component to select when the canvas opens.",
        },
    },
};

const focusActionSchema = {
    type: "object",
    additionalProperties: false,
    required: ["component_id"],
    properties: {
        component_id: {
            type: "string",
            enum: COMPONENT_IDS,
            description: "Component id to describe.",
        },
    },
};

function escapeHtml(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
}

function findNode(componentId) {
    return LAID_OUT_ARCHITECTURE.nodes.find((node) => node.id === componentId);
}

function componentContext(componentId) {
    const component = findNode(componentId);
    if (!component) {
        throw new CanvasError("component_not_found", `Unknown architecture component: ${componentId}`);
    }

    return {
        component,
        incoming: LAID_OUT_ARCHITECTURE.edges.filter((edge) => edge.to === componentId),
        outgoing: LAID_OUT_ARCHITECTURE.edges.filter((edge) => edge.from === componentId),
    };
}

function normalizeFocus(input) {
    if (input && typeof input.focus === "string") {
        return input.focus;
    }

    return "pier-backend";
}

function writeResponse(res, statusCode, contentType, body) {
    res.writeHead(statusCode, {
        "Cache-Control": "no-store",
        "Content-Type": contentType,
    });
    res.end(body);
}

function renderHtml(instanceId, focus) {
    const data = JSON.stringify(LAID_OUT_ARCHITECTURE);
    const initialFocus = JSON.stringify(focus);
    const escapedInstanceId = escapeHtml(instanceId);

    return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>copilot-experiments architecture</title>
<style>
:root {
    color-scheme: light dark;
    --node-width: 198px;
    --node-height: 86px;
}

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    background:
        radial-gradient(circle at top left, color-mix(in srgb, var(--true-color-blue-muted, #ddf4ff) 45%, transparent), transparent 34rem),
        var(--background-color-default, #ffffff);
    color: var(--text-color-default, #1f2328);
    font-family: var(--font-sans, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif);
    font-size: var(--text-body-medium, 14px);
    line-height: var(--leading-body-medium, 20px);
}

button,
input {
    font: inherit;
}

.shell {
    min-height: 100vh;
    padding: 24px;
}

.hero {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 18px;
    align-items: start;
    margin-bottom: 18px;
}

.eyebrow {
    color: var(--text-color-muted, #656d76);
    font-size: 12px;
    font-weight: var(--font-weight-semibold, 600);
    letter-spacing: 0.08em;
    margin-bottom: 8px;
    text-transform: uppercase;
}

h1 {
    font-family: var(--font-sans-display, var(--font-sans, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif));
    font-size: var(--text-title-large, 28px);
    font-weight: var(--font-weight-semibold, 600);
    line-height: var(--leading-title-large, 34px);
    margin: 0 0 8px;
}

.tagline {
    color: var(--text-color-muted, #656d76);
    margin: 0;
    max-width: 860px;
}

.meta-card {
    background: color-mix(in srgb, var(--background-color-default, #ffffff) 82%, var(--true-color-blue-muted, #ddf4ff));
    border: 1px solid var(--border-color-default, #d0d7de);
    border-radius: 14px;
    min-width: 250px;
    padding: 14px;
}

.meta-card strong {
    display: block;
    font-size: 13px;
    margin-bottom: 4px;
}

.meta-card code {
    color: var(--text-color-muted, #656d76);
    font-family: var(--font-mono, "SFMono-Regular", Consolas, "Liberation Mono", monospace);
    font-size: var(--text-code-inline, 12px);
}

.toolbar {
    align-items: center;
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin: 0 0 16px;
}

.pill {
    background: var(--background-color-default, #ffffff);
    border: 1px solid var(--border-color-default, #d0d7de);
    border-radius: 999px;
    color: var(--text-color-default, #1f2328);
    cursor: pointer;
    padding: 7px 12px;
}

.pill[aria-pressed="true"],
.pill:hover {
    background: var(--true-color-blue-muted, #ddf4ff);
    border-color: var(--true-color-blue, #0969da);
}

.layout {
    display: grid;
    gap: 18px;
    grid-template-columns: minmax(820px, 1fr) 360px;
}

.canvas-card,
.details-card,
.invariants-card {
    background: color-mix(in srgb, var(--background-color-default, #ffffff) 94%, var(--border-color-default, #d0d7de));
    border: 1px solid var(--border-color-default, #d0d7de);
    border-radius: 18px;
    box-shadow: 0 16px 44px color-mix(in srgb, var(--text-color-default, #1f2328) 9%, transparent);
}

.canvas-card {
    overflow: hidden;
}

.legend {
    align-items: center;
    border-bottom: 1px solid var(--border-color-default, #d0d7de);
    display: flex;
    flex-wrap: wrap;
    gap: 14px;
    justify-content: space-between;
    padding: 14px 16px;
}

.legend-items {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
}

.legend-item {
    align-items: center;
    color: var(--text-color-muted, #656d76);
    display: inline-flex;
    font-size: 12px;
    gap: 6px;
}

.swatch {
    border-radius: 999px;
    display: inline-block;
    height: 8px;
    width: 24px;
}

.swatch.control { background: var(--true-color-blue, #0969da); }
.swatch.telemetry { background: var(--true-color-red, #cf222e); }
.swatch.artifact { background: #8250df; }
.swatch.analysis { background: #1a7f37; }

.hint {
    color: var(--text-color-muted, #656d76);
    font-size: 12px;
}

.diagram-wrap {
    overflow: auto;
    padding: 10px;
}

svg {
    display: block;
    width: 100%;
}

.lane-band {
    fill: color-mix(in srgb, var(--lane-color) 7%, transparent);
    stroke: color-mix(in srgb, var(--lane-color) 24%, transparent);
    stroke-dasharray: 4 8;
    stroke-width: 1;
}

.lane-label {
    fill: var(--text-color-muted, #656d76);
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
}

.edge {
    fill: none;
    opacity: 0.46;
    stroke-linecap: round;
    stroke-linejoin: round;
    stroke-width: 1.8;
    vector-effect: non-scaling-stroke;
}

.edge.control { stroke: var(--true-color-blue, #0969da); }
.edge.telemetry { stroke: var(--true-color-red, #cf222e); }
.edge.artifact { stroke: #8250df; }
.edge.analysis { stroke: #1a7f37; }
.edge.dimmed { opacity: 0.09; }
.edge.active {
    filter: drop-shadow(0 0 4px color-mix(in srgb, var(--true-color-blue, #0969da) 32%, transparent));
    opacity: 1;
    stroke-width: 2.8;
}

.arrow-head {
    stroke: none;
}

.arrow-head.control { fill: var(--true-color-blue, #0969da); }
.arrow-head.telemetry { fill: var(--true-color-red, #cf222e); }
.arrow-head.artifact { fill: #8250df; }
.arrow-head.analysis { fill: #1a7f37; }

.edge.dimmed + .edge-label-bg + .edge-label,
.edge.dimmed + .edge-label-bg {
    opacity: 0;
}

.edge-label {
    fill: var(--text-color-muted, #656d76);
    font-size: 10px;
    pointer-events: none;
}

.edge-label-bg {
    fill: color-mix(in srgb, var(--background-color-default, #ffffff) 86%, transparent);
    opacity: 0.82;
    pointer-events: none;
    stroke: color-mix(in srgb, var(--border-color-default, #d0d7de) 75%, transparent);
}

.edge-label-bg.dimmed { opacity: 0; }
.edge-label-bg.active {
    fill: var(--background-color-default, #ffffff);
    opacity: 1;
    stroke: var(--true-color-blue, #0969da);
}

.edge-label.dimmed { opacity: 0; }
.edge-label.active {
    fill: var(--text-color-default, #1f2328);
    font-weight: 600;
}

.node-card {
    cursor: pointer;
    outline: none;
}

.node-surface {
    background: var(--background-color-default, #ffffff);
    border: 1px solid var(--border-color-default, #d0d7de);
    border-left: 6px solid var(--lane-color);
    border-radius: 14px;
    height: var(--node-height);
    padding: 11px 12px;
    transition:
        background 120ms ease,
        border-color 120ms ease,
        box-shadow 120ms ease,
        transform 120ms ease;
}

.node-card:hover .node-surface,
.node-card:focus-visible .node-surface {
    border-color: var(--true-color-blue, #0969da);
    box-shadow: 0 12px 28px color-mix(in srgb, var(--true-color-blue, #0969da) 18%, transparent);
    transform: translateY(-1px);
}

.node-card.selected .node-surface {
    background: color-mix(in srgb, var(--true-color-blue-muted, #ddf4ff) 48%, var(--background-color-default, #ffffff));
    border-color: var(--true-color-blue, #0969da);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--true-color-blue, #0969da) 18%, transparent);
}

.node-card.related .node-surface {
    border-color: color-mix(in srgb, var(--lane-color) 62%, var(--border-color-default, #d0d7de));
}

.node-card.dimmed {
    opacity: 0.35;
}

.node-title {
    color: var(--text-color-default, #1f2328);
    font-size: 13px;
    font-weight: 700;
    line-height: 16px;
    margin-bottom: 5px;
}

.node-subtitle {
    color: var(--text-color-muted, #656d76);
    font-size: 11px;
    line-height: 14px;
}

.side {
    display: grid;
    gap: 18px;
}

.details-card,
.invariants-card {
    padding: 18px;
}

.details-card h2,
.invariants-card h2 {
    font-size: 16px;
    line-height: 22px;
    margin: 0 0 8px;
}

.layer-badge {
    background: var(--true-color-blue-muted, #ddf4ff);
    border: 1px solid var(--true-color-blue, #0969da);
    border-radius: 999px;
    color: var(--text-color-default, #1f2328);
    display: inline-block;
    font-size: 12px;
    font-weight: 600;
    margin-bottom: 12px;
    padding: 3px 8px;
}

.details-text {
    color: var(--text-color-default, #1f2328);
    margin: 0 0 14px;
}

.files {
    display: grid;
    gap: 6px;
    margin: 12px 0 16px;
}

.file {
    background: color-mix(in srgb, var(--background-color-default, #ffffff) 86%, var(--border-color-default, #d0d7de));
    border: 1px solid var(--border-color-default, #d0d7de);
    border-radius: 8px;
    color: var(--text-color-muted, #656d76);
    font-family: var(--font-mono, "SFMono-Regular", Consolas, "Liberation Mono", monospace);
    font-size: 12px;
    padding: 6px 8px;
}

.flow-list {
    display: grid;
    gap: 8px;
}

.flow-item {
    border-left: 3px solid var(--true-color-blue, #0969da);
    color: var(--text-color-muted, #656d76);
    font-size: 12px;
    padding-left: 9px;
}

.flow-item strong {
    color: var(--text-color-default, #1f2328);
    display: block;
    font-size: 13px;
}

.invariants-card ol {
    margin: 0;
    padding-left: 20px;
}

.invariants-card li {
    margin: 0 0 8px;
}

@media (max-width: 1180px) {
    .hero,
    .layout {
        grid-template-columns: 1fr;
    }

    .meta-card {
        min-width: 0;
    }
}
</style>
</head>
<body>
<main class="shell">
    <section class="hero">
        <div>
            <div class="eyebrow">Architecture visualization</div>
            <h1>copilot-experiments</h1>
            <p class="tagline">${escapeHtml(ARCHITECTURE.tagline)}</p>
        </div>
        <div class="meta-card">
            <strong>Canvas instance</strong>
            <code>${escapedInstanceId}</code>
        </div>
    </section>

    <nav class="toolbar" aria-label="Architecture layers" id="layerFilters"></nav>

    <section class="layout">
        <article class="canvas-card">
            <div class="legend">
                <div class="legend-items">
                    <span class="legend-item"><span class="swatch control"></span>Control flow</span>
                    <span class="legend-item"><span class="swatch telemetry"></span>Telemetry</span>
                    <span class="legend-item"><span class="swatch artifact"></span>Artifacts</span>
                    <span class="legend-item"><span class="swatch analysis"></span>Analysis</span>
                </div>
                <span class="hint">Click any component to focus its dependencies and outputs.</span>
            </div>
            <div class="diagram-wrap">
                <svg id="diagram" role="img" aria-label="copilot-experiments architecture diagram"></svg>
            </div>
        </article>

        <aside class="side">
            <section class="details-card" id="details" aria-live="polite"></section>
            <section class="invariants-card">
                <h2>Design invariants</h2>
                <ol id="invariants"></ol>
            </section>
        </aside>
    </section>
</main>

<script>
const architecture = ${data};
const initialFocus = ${initialFocus};
const svg = document.querySelector("#diagram");
const details = document.querySelector("#details");
const layerFilters = document.querySelector("#layerFilters");
const invariants = document.querySelector("#invariants");
const layerColors = {
    authoring: "#8250df",
    interface: "var(--true-color-blue, #0969da)",
    execution: "#bf8700",
    agent: "var(--true-color-red, #cf222e)",
    capture: "#57606a",
    analysis: "#1a7f37",
};

let selectedId = initialFocus;
let activeLayer = "all";

function byId(id) {
    return architecture.nodes.find((node) => node.id === id);
}

function relatedIds(id) {
    const ids = new Set([id]);
    for (const edge of architecture.edges) {
        if (edge.from === id) ids.add(edge.to);
        if (edge.to === id) ids.add(edge.from);
    }
    return ids;
}

function activeEdges(id) {
    return new Set(
        architecture.edges
            .filter((edge) => edge.from === id || edge.to === id)
            .map((edge) => edge.from + "->" + edge.to),
    );
}

function element(name, attrs = {}, children = []) {
    const el = document.createElementNS("http://www.w3.org/2000/svg", name);
    for (const [key, value] of Object.entries(attrs)) {
        el.setAttribute(key, value);
    }
    for (const child of children) {
        el.appendChild(child);
    }
    return el;
}

function htmlElement(name, attrs = {}, children = []) {
    const el = document.createElement(name);
    for (const [key, value] of Object.entries(attrs)) {
        if (key === "className") {
            el.className = value;
        } else if (key === "text") {
            el.textContent = value;
        } else {
            el.setAttribute(key, value);
        }
    }
    for (const child of children) {
        el.appendChild(child);
    }
    return el;
}

function renderFilters() {
    layerFilters.replaceChildren();
    const all = htmlElement("button", {
        className: "pill",
        type: "button",
        "aria-pressed": activeLayer === "all" ? "true" : "false",
        text: "All layers",
    });
    all.addEventListener("click", () => {
        activeLayer = "all";
        render();
    });
    layerFilters.appendChild(all);

    for (const layer of architecture.layers) {
        const button = htmlElement("button", {
            className: "pill",
            type: "button",
            "aria-pressed": activeLayer === layer.id ? "true" : "false",
            text: layer.name,
        });
        button.addEventListener("click", () => {
            activeLayer = layer.id;
            render();
        });
        layerFilters.appendChild(button);
    }
}

function renderDiagram() {
    svg.replaceChildren();
    svg.setAttribute("viewBox", "0 0 " + architecture.layout.width + " " + architecture.layout.height);

    const defs = element("defs");
    for (const kind of ["control", "telemetry", "artifact", "analysis"]) {
        const marker = element("marker", {
            id: "arrow-" + kind,
            markerWidth: "8",
            markerHeight: "8",
            refX: "7",
            refY: "4",
            orient: "auto-start-reverse",
            markerUnits: "userSpaceOnUse",
        });
        const path = element("path", {
            d: "M0,0 L8,4 L0,8 L2.2,4 Z",
            class: "arrow-head " + kind,
        });
        marker.appendChild(path);
        defs.appendChild(marker);
    }
    svg.appendChild(defs);

    const laneGroup = element("g");
    for (const lane of architecture.lanes) {
        laneGroup.appendChild(element("rect", {
            class: "lane-band",
            x: String(lane.x),
            y: String(lane.y),
            width: String(lane.width),
            height: String(lane.height),
            rx: "18",
            style: "--lane-color: " + layerColors[lane.id],
        }));
        laneGroup.appendChild(element("text", {
            class: "lane-label",
            x: String(lane.labelX),
            y: String(lane.labelY),
        }, [document.createTextNode(lane.name)]));
    }
    svg.appendChild(laneGroup);

    const related = relatedIds(selectedId);
    const selectedEdges = activeEdges(selectedId);

    const edgeGroup = element("g");
    for (const edge of architecture.edges) {
        const key = edge.from + "->" + edge.to;
        const active = selectedEdges.has(key);
        const dimmed = !active && selectedId;
        edgeGroup.appendChild(element("path", {
            class: "edge " + edge.kind + (active ? " active" : dimmed ? " dimmed" : ""),
            d: edge.d,
            "marker-end": "url(#arrow-" + edge.kind + ")",
        }));
        edgeGroup.appendChild(element("rect", {
            class: "edge-label-bg" + (active ? " active" : dimmed ? " dimmed" : ""),
            x: String(edge.labelX - edge.labelWidth / 2),
            y: String(edge.labelY - 11),
            width: String(edge.labelWidth),
            height: "17",
            rx: "8",
        }));
        edgeGroup.appendChild(element("text", {
            class: "edge-label" + (active ? " active" : dimmed ? " dimmed" : ""),
            x: String(edge.labelX),
            y: String(edge.labelY + 1),
            "text-anchor": "middle",
        }, [document.createTextNode(edge.label)]));
    }
    svg.appendChild(edgeGroup);

    const nodeGroup = element("g");
    for (const node of architecture.nodes) {
        const layerHidden = activeLayer !== "all" && node.layer !== activeLayer;
        const isSelected = node.id === selectedId;
        const isRelated = related.has(node.id);
        const foreign = element("foreignObject", {
            class:
                "node-card" +
                (isSelected ? " selected" : "") +
                (isRelated && !isSelected ? " related" : "") +
                ((!isRelated || layerHidden) ? " dimmed" : ""),
            x: String(node.x),
            y: String(node.y),
            width: String(node.width),
            height: String(node.height),
            tabindex: "0",
            role: "button",
            "aria-label": node.title,
            "data-node-id": node.id,
        });
        const surface = htmlElement("div", {
            className: "node-surface",
            style: "--lane-color: " + layerColors[node.layer],
        }, [
            htmlElement("div", { className: "node-title", text: node.title }),
            htmlElement("div", { className: "node-subtitle", text: node.subtitle }),
        ]);
        foreign.appendChild(surface);
        foreign.addEventListener("click", () => selectNode(node.id));
        foreign.addEventListener("keydown", (event) => {
            if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                selectNode(node.id);
            }
        });
        nodeGroup.appendChild(foreign);
    }
    svg.appendChild(nodeGroup);
}

function renderDetails() {
    const node = byId(selectedId) || architecture.nodes[0];
    const layer = architecture.layers.find((item) => item.id === node.layer);
    const incoming = architecture.edges.filter((edge) => edge.to === node.id);
    const outgoing = architecture.edges.filter((edge) => edge.from === node.id);

    details.replaceChildren(
        htmlElement("span", { className: "layer-badge", text: layer ? layer.name : node.layer }),
        htmlElement("h2", { text: node.title }),
        htmlElement("p", { className: "details-text", text: node.details }),
        htmlElement("h2", { text: "Key files" }),
        htmlElement("div", { className: "files" }, node.files.map((file) => htmlElement("div", { className: "file", text: file }))),
        htmlElement("h2", { text: "Focused flow" }),
        htmlElement("div", { className: "flow-list" }, [
            ...incoming.map((edge) =>
                htmlElement("div", { className: "flow-item" }, [
                    htmlElement("strong", { text: (byId(edge.from)?.title || edge.from) + " -> " + node.title }),
                    document.createTextNode(edge.label),
                ]),
            ),
            ...outgoing.map((edge) =>
                htmlElement("div", { className: "flow-item" }, [
                    htmlElement("strong", { text: node.title + " -> " + (byId(edge.to)?.title || edge.to) }),
                    document.createTextNode(edge.label),
                ]),
            ),
        ]),
    );
}

function renderInvariants() {
    invariants.replaceChildren(
        ...architecture.invariants.map((item) => htmlElement("li", { text: item })),
    );
}

function selectNode(id) {
    selectedId = id;
    renderDiagram();
    renderDetails();
}

function render() {
    renderFilters();
    renderDiagram();
    renderDetails();
    renderInvariants();
}

render();
</script>
</body>
</html>`;
}

function handleRequest(req, res, instanceId, state) {
    const url = new URL(req.url ?? "/", "http://127.0.0.1");

    if (req.method !== "GET") {
        writeResponse(res, 405, "text/plain; charset=utf-8", "Method not allowed");
        return;
    }

    if (url.pathname === "/") {
        writeResponse(res, 200, "text/html; charset=utf-8", renderHtml(instanceId, state.focus));
        return;
    }

    if (url.pathname === "/architecture.json") {
        writeResponse(
            res,
            200,
            "application/json; charset=utf-8",
            JSON.stringify(LAID_OUT_ARCHITECTURE),
        );
        return;
    }

    writeResponse(res, 404, "text/plain; charset=utf-8", "Not found");
}

async function startServer(instanceId) {
    const state = { focus: "pier-backend" };
    const server = createServer((req, res) => handleRequest(req, res, instanceId, state));
    await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    const port = typeof address === "object" && address ? address.port : 0;
    return { server, state, url: `http://127.0.0.1:${port}/` };
}

await joinSession({
    canvases: [
        createCanvas({
            id: "architecture-visualizer",
            displayName: "Architecture Visualizer",
            description:
                "Interactive architecture diagram for the copilot-experiments application.",
            inputSchema: openInputSchema,
            actions: [
                {
                    name: "get_architecture",
                    description: "Return the architecture nodes, edges, layers, and invariants.",
                    handler: () => LAID_OUT_ARCHITECTURE,
                },
                {
                    name: "focus_component",
                    description:
                        "Return details and connected flows for a specific architecture component.",
                    inputSchema: focusActionSchema,
                    handler: (ctx) => componentContext(ctx.input.component_id),
                },
            ],
            open: async (ctx) => {
                let entry = servers.get(ctx.instanceId);
                if (!entry) {
                    entry = await startServer(ctx.instanceId);
                    servers.set(ctx.instanceId, entry);
                }
                entry.state.focus = normalizeFocus(ctx.input);

                return {
                    title: "copilot-experiments architecture",
                    status: "Interactive module and data-flow visualization",
                    url: entry.url,
                };
            },
            onClose: async (ctx) => {
                const entry = servers.get(ctx.instanceId);
                if (entry) {
                    servers.delete(ctx.instanceId);
                    await new Promise((resolve) => entry.server.close(() => resolve()));
                }
            },
        }),
    ],
});
