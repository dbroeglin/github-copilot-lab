import { createServer } from "node:http";
import { createCanvas, joinSession } from "@github/copilot-sdk/extension";

const servers = new Map();

const structure = [
    {
        id: "repo",
        parent: null,
        label: "Experiment repository",
        path: ".",
        kind: "root",
        badge: "workspace",
        owner: "human + harness",
        source: "The git checkout that contains experiment definitions and generated outputs.",
        why: "Separates experiment authoring from the copilot-experiments harness repository.",
        commands: ["copilot-experiments list", "copilot-experiments validate"],
    },
    {
        id: "experiments",
        parent: "repo",
        label: "experiments/",
        path: "experiments/",
        kind: "source",
        badge: "committed",
        owner: "experiment author",
        source: "Pier JobConfig YAML files.",
        why: "Defines what to run: tasks, agents, model settings, attempts, concurrency, and job_name.",
        commands: ["copilot-experiments validate", "copilot-experiments run [job-name]"],
    },
    {
        id: "job-yaml",
        parent: "experiments",
        label: "<job>.yaml",
        path: "experiments/<job>.yaml",
        kind: "source",
        badge: "committed",
        owner: "experiment author",
        source: "Stable Pier job configuration.",
        why: "The job_name is the durable experiment identity. Repeated executions keep this identity but get new run ids.",
        commands: ["copilot-experiments run <job-name>", "copilot-experiments run --resume <job-name>"],
    },
    {
        id: "tasks",
        parent: "repo",
        label: "tasks/",
        path: "tasks/",
        kind: "task",
        badge: "committed",
        owner: "experiment author",
        source: "Harbor/Pier task directories or imported task corpora.",
        why: "Keeps task instructions, environment setup, and verifiers close to the experiment repo.",
        commands: ["copilot-experiments deepswe-import <source>", "copilot-experiments validate"],
    },
    {
        id: "task-dir",
        parent: "tasks",
        label: "<task>/",
        path: "tasks/<task>/",
        kind: "task",
        badge: "committed",
        owner: "experiment author",
        source: "One task's prompt, environment, and verifier.",
        why: "A Pier job can point to individual tasks or datasets of many tasks.",
        commands: ["copilot-experiments validate"],
    },
    {
        id: "task-instruction",
        parent: "task-dir",
        label: "instruction.md",
        path: "tasks/<task>/instruction.md",
        kind: "task",
        badge: "committed",
        owner: "experiment author",
        source: "Prompt text presented to the evaluated agent.",
        why: "This is the human-readable task objective.",
        commands: [],
    },
    {
        id: "task-toml",
        parent: "task-dir",
        label: "task.toml",
        path: "tasks/<task>/task.toml",
        kind: "task",
        badge: "committed",
        owner: "experiment author",
        source: "Pier task metadata.",
        why: "Connects instructions, environment, and verifier into a runnable task.",
        commands: [],
    },
    {
        id: "task-env",
        parent: "task-dir",
        label: "environment/",
        path: "tasks/<task>/environment/",
        kind: "task",
        badge: "committed",
        owner: "experiment author",
        source: "Sandbox setup for the task.",
        why: "Gives Pier a reproducible workspace for each trial.",
        commands: [],
    },
    {
        id: "task-tests",
        parent: "task-dir",
        label: "tests/",
        path: "tasks/<task>/tests/",
        kind: "task",
        badge: "committed",
        owner: "experiment author",
        source: "Verifier inputs or grading scripts.",
        why: "Turns an agent patch into an objective success signal.",
        commands: [],
    },
    {
        id: "jobs",
        parent: "repo",
        label: "jobs/",
        path: "jobs/",
        kind: "run",
        badge: "gitignored",
        owner: "Pier + harness",
        source: "Generated run outputs. This is now the primary execution tree.",
        why: "Keeps measured executions out of git while preserving all data needed to inspect a run.",
        commands: ["copilot-experiments list"],
    },
    {
        id: "job-group",
        parent: "jobs",
        label: "<job-name>/",
        path: "jobs/<job-name>/",
        kind: "run",
        badge: "stable identity",
        owner: "copilot-experiments",
        source: "Grouping directory named from the configured Pier job_name.",
        why: "A stable identity can contain many repeated measurements without inventing new job names.",
        commands: ["copilot-experiments show <job-name>", "copilot-experiments inspect <job-name>"],
    },
    {
        id: "run-dir",
        parent: "job-group",
        label: "<run-id>/",
        path: "jobs/<job-name>/<run-id>/",
        kind: "run",
        badge: "generated",
        owner: "Pier + harness",
        source: "One concrete execution, usually timestamped like 20260620-153000.",
        why: "This is the copyable run selector: <job-name>/<run-id>.",
        commands: [
            "copilot-experiments show <job-name>/<run-id>",
            "copilot-experiments inspect <job-name>/<run-id>",
            "copilot-experiments analyze <job-name>/<run-id> --trial 1",
        ],
    },
    {
        id: "run-manifest",
        parent: "run-dir",
        label: "copilot-experiments-run.json",
        path: "jobs/<job-name>/<run-id>/copilot-experiments-run.json",
        kind: "run",
        badge: "harness",
        owner: "copilot-experiments",
        source: "Small manifest with job_name, run_id, and job/run id.",
        why: "Pier's config sees the concrete run id as job_name; this manifest preserves the stable job identity.",
        commands: [],
    },
    {
        id: "run-config",
        parent: "run-dir",
        label: "config.json",
        path: "jobs/<job-name>/<run-id>/config.json",
        kind: "run",
        badge: "Pier",
        owner: "Pier",
        source: "Resolved Pier job config for this concrete execution.",
        why: "Captures exactly what Pier ran after path normalization and agent setup.",
        commands: [],
    },
    {
        id: "run-result",
        parent: "run-dir",
        label: "result.json",
        path: "jobs/<job-name>/<run-id>/result.json",
        kind: "run",
        badge: "Pier",
        owner: "Pier",
        source: "Job-level status, timings, and aggregate Pier stats.",
        why: "Primary job status signal for show and list.",
        commands: ["copilot-experiments show <job-name>/<run-id>"],
    },
    {
        id: "trial-dir",
        parent: "run-dir",
        label: "<trial-name>/",
        path: "jobs/<job-name>/<run-id>/<trial-name>/",
        kind: "trial",
        badge: "generated",
        owner: "Pier",
        source: "One agent/task/attempt cell.",
        why: "Contains the raw evidence for whether a task was solved and how the agent behaved.",
        commands: ["copilot-experiments inspect <job-name>/<run-id> --trial 1"],
    },
    {
        id: "trial-config",
        parent: "trial-dir",
        label: "config.json",
        path: "jobs/<job-name>/<run-id>/<trial-name>/config.json",
        kind: "trial",
        badge: "Pier",
        owner: "Pier",
        source: "Resolved trial configuration.",
        why: "Useful when comparing why two trial cells differ.",
        commands: [],
    },
    {
        id: "trial-result",
        parent: "trial-dir",
        label: "result.json",
        path: "jobs/<job-name>/<run-id>/<trial-name>/result.json",
        kind: "trial",
        badge: "Pier",
        owner: "Pier",
        source: "Trial status, verifier reward, exceptions, agent info, and timings.",
        why: "This is where harness failures and grading results are diagnosed.",
        commands: ["copilot-experiments inspect <job-name>/<run-id> --trial 1"],
    },
    {
        id: "agent",
        parent: "trial-dir",
        label: "agent/",
        path: "jobs/<job-name>/<run-id>/<trial-name>/agent/",
        kind: "analysis",
        badge: "agent output",
        owner: "copilot-cli agent",
        source: "Outputs captured from the evaluated agent.",
        why: "Raw agent evidence lives here; summaries are derived from these files.",
        commands: ["copilot-experiments analyze <job-name>/<run-id> --trial 1"],
    },
    {
        id: "trajectory",
        parent: "agent",
        label: "trajectory.json",
        path: ".../agent/trajectory.json",
        kind: "analysis",
        badge: "ATIF",
        owner: "copilot-cli agent",
        source: "ATIF trajectory emitted by the installed agent.",
        why: "Fallback analysis source when native Copilot session events are absent.",
        commands: ["copilot-experiments analyze <job-name>/<run-id> --trial 1"],
    },
    {
        id: "cli-jsonl",
        parent: "agent",
        label: "copilot-cli.jsonl / .txt",
        path: ".../agent/copilot-cli.jsonl",
        kind: "analysis",
        badge: "diagnostic",
        owner: "copilot-cli agent",
        source: "Raw Copilot CLI output streams.",
        why: "Useful for auth, invocation, or startup failures before a session log exists.",
        commands: [],
    },
    {
        id: "otel",
        parent: "agent",
        label: "copilot-otel.jsonl",
        path: ".../agent/copilot-otel.jsonl",
        kind: "analysis",
        badge: "diagnostic",
        owner: "copilot-cli agent",
        source: "OpenTelemetry file exporter output for Copilot calls.",
        why: "Enriches analysis with per-LLM-call metrics and AIU details.",
        commands: ["copilot-experiments analyze --file <events.jsonl> --otel-file <copilot-otel.jsonl>"],
    },
    {
        id: "session-events",
        parent: "agent",
        label: "copilot-session/**/events.jsonl",
        path: ".../agent/copilot-session/<session-id>/events.jsonl",
        kind: "analysis",
        badge: "source of truth",
        owner: "GitHub Copilot CLI",
        source: "Native Copilot CLI session log.",
        why: "Primary source for turns, tool calls, tokens, AIU, and rich analysis.",
        commands: [
            "copilot-experiments analyze <job-name>/<run-id> --trial 1",
            "copilot-experiments analyze --file <events.jsonl>",
        ],
    },
    {
        id: "verifier",
        parent: "trial-dir",
        label: "verifier/",
        path: ".../<trial-name>/verifier/",
        kind: "trial",
        badge: "Pier",
        owner: "Pier verifier",
        source: "Verifier outputs, rewards, and grading artifacts.",
        why: "Connects agent behavior to the solved/unsolved measurement.",
        commands: [],
    },
    {
        id: "artifacts",
        parent: "trial-dir",
        label: "artifacts/",
        path: ".../<trial-name>/artifacts/",
        kind: "trial",
        badge: "Pier",
        owner: "Pier",
        source: "Downloaded artifacts requested by the job config.",
        why: "Keeps extra run evidence beside the trial that produced it.",
        commands: [],
    },
    {
        id: "summary",
        parent: "run-dir",
        label: "summary.json / summary.md",
        path: "jobs/<job-name>/<run-id>/summary.json",
        kind: "derived",
        badge: "derived",
        owner: "copilot-experiments",
        source: "Generated from Pier result files and Copilot-native logs.",
        why: "Gives the agent/task aggregate shape for show and reports.",
        commands: ["copilot-experiments show <job-name>/<run-id>"],
    },
    {
        id: "guidance",
        parent: "repo",
        label: "README.md / AGENTS.md / .apm/",
        path: "README.md, AGENTS.md, .apm/",
        kind: "guidance",
        badge: "committed",
        owner: "experiment author",
        source: "Human and agent guidance for the experiment repo.",
        why: "Makes the repo self-explanatory for people and for Copilot agents working inside it.",
        commands: ["copilot-experiments list"],
    },
];

const flow = [
    ["Author task", "tasks/<task>/instruction.md"],
    ["Define job", "experiments/<job>.yaml"],
    ["Run", "copilot-experiments run"],
    ["Concrete output", "jobs/<job-name>/<run-id>/"],
    ["Inspect/analyze", "show | inspect | analyze <job-name>/<run-id>"],
    ["Summarize", "summary.json / summary.md"],
];

function htmlEscape(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
}

function renderHtml() {
    const data = JSON.stringify(structure).replaceAll("<", "\\u003c");
    const flowData = JSON.stringify(flow).replaceAll("<", "\\u003c");
    return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Experiment repository structure</title>
<style>
:root {
    color-scheme: light dark;
}
* {
    box-sizing: border-box;
}
body {
    margin: 0;
    background: var(--background-color-default, #ffffff);
    color: var(--text-color-default, #1f2328);
    font-family: var(--font-sans, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif);
    font-size: var(--text-body-medium, 14px);
    line-height: var(--leading-body-medium, 20px);
}
main {
    min-height: 100vh;
    display: grid;
    grid-template-rows: auto auto 1fr;
}
header {
    padding: 20px 24px 14px;
    border-bottom: 1px solid var(--border-color-default, #d0d7de);
    background: linear-gradient(135deg, var(--background-color-default, #fff), rgba(47, 129, 247, 0.08));
}
h1 {
    margin: 0 0 8px;
    font-family: var(--font-sans-display, var(--font-sans, inherit));
    font-size: var(--text-title-large, 26px);
    line-height: var(--leading-title-large, 32px);
    font-weight: var(--font-weight-semibold, 600);
}
.lede {
    max-width: 980px;
    color: var(--text-color-muted, #57606a);
    margin: 0;
}
.flow {
    display: grid;
    grid-template-columns: repeat(6, minmax(120px, 1fr));
    gap: 8px;
    padding: 14px 24px;
    border-bottom: 1px solid var(--border-color-default, #d0d7de);
    background: color-mix(in srgb, var(--background-color-default, #fff) 94%, var(--true-color-blue, #0969da));
}
.flow-step {
    border: 1px solid var(--border-color-default, #d0d7de);
    border-radius: 12px;
    padding: 10px;
    background: var(--background-color-default, #ffffff);
    position: relative;
    min-height: 82px;
}
.flow-step:not(:last-child)::after {
    content: ">";
    position: absolute;
    right: -12px;
    top: 31px;
    color: var(--text-color-muted, #57606a);
    font-weight: var(--font-weight-semibold, 600);
}
.flow-title {
    display: block;
    font-weight: var(--font-weight-semibold, 600);
    margin-bottom: 6px;
}
.flow-path {
    color: var(--text-color-muted, #57606a);
    font-family: var(--font-mono, ui-monospace, SFMono-Regular, Consolas, monospace);
    font-size: var(--text-code-inline, 12px);
    overflow-wrap: anywhere;
}
.workspace {
    display: grid;
    grid-template-columns: minmax(360px, 48%) minmax(320px, 1fr);
    min-height: 0;
}
.left {
    border-right: 1px solid var(--border-color-default, #d0d7de);
    min-width: 0;
    overflow: auto;
}
.right {
    min-width: 0;
    overflow: auto;
    background: color-mix(in srgb, var(--background-color-default, #fff) 97%, var(--true-color-blue, #0969da));
}
.controls {
    position: sticky;
    top: 0;
    z-index: 1;
    padding: 12px 16px;
    border-bottom: 1px solid var(--border-color-default, #d0d7de);
    background: var(--background-color-default, #ffffff);
}
.search {
    width: 100%;
    border: 1px solid var(--border-color-default, #d0d7de);
    border-radius: 8px;
    padding: 8px 10px;
    color: var(--text-color-default, #1f2328);
    background: var(--background-color-default, #ffffff);
    font: inherit;
}
.chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 10px;
}
button {
    font: inherit;
}
.chip {
    border: 1px solid var(--border-color-default, #d0d7de);
    color: var(--text-color-default, #1f2328);
    background: var(--background-color-default, #ffffff);
    border-radius: 999px;
    padding: 4px 9px;
    cursor: pointer;
}
.chip.active {
    border-color: var(--true-color-blue, #0969da);
    background: var(--true-color-blue-muted, rgba(47, 129, 247, 0.12));
}
.tree {
    padding: 12px 12px 28px;
}
.node {
    display: grid;
    grid-template-columns: 20px 1fr auto;
    align-items: center;
    gap: 7px;
    width: 100%;
    border: 0;
    border-radius: 8px;
    background: transparent;
    color: var(--text-color-default, #1f2328);
    padding: 7px 8px;
    text-align: left;
    cursor: pointer;
}
.node:hover,
.node.selected {
    background: var(--true-color-blue-muted, rgba(47, 129, 247, 0.12));
}
.twisty {
    color: var(--text-color-muted, #57606a);
    width: 16px;
    display: inline-block;
}
.label {
    min-width: 0;
}
.label code,
.path,
.command {
    font-family: var(--font-mono, ui-monospace, SFMono-Regular, Consolas, monospace);
}
.badge {
    border-radius: 999px;
    border: 1px solid var(--border-color-default, #d0d7de);
    color: var(--text-color-muted, #57606a);
    padding: 1px 7px;
    font-size: 12px;
}
.children {
    margin-left: 20px;
    padding-left: 9px;
    border-left: 1px solid var(--border-color-default, #d0d7de);
}
.detail {
    padding: 22px 24px 36px;
    max-width: 920px;
}
.detail h2 {
    margin: 0 0 4px;
    font-size: 22px;
    line-height: 28px;
}
.detail .path {
    display: inline-block;
    margin: 6px 0 14px;
    color: var(--text-color-muted, #57606a);
    background: color-mix(in srgb, var(--background-color-default, #fff) 90%, var(--true-color-blue, #0969da));
    border: 1px solid var(--border-color-default, #d0d7de);
    border-radius: 8px;
    padding: 5px 8px;
    overflow-wrap: anywhere;
}
.meta {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 8px;
    margin: 10px 0 16px;
}
.meta-card,
.callout,
.commands {
    border: 1px solid var(--border-color-default, #d0d7de);
    border-radius: 12px;
    background: var(--background-color-default, #ffffff);
}
.meta-card {
    padding: 10px;
}
.meta-card strong {
    display: block;
    margin-bottom: 3px;
}
.meta-card span {
    color: var(--text-color-muted, #57606a);
}
.callout {
    padding: 13px 14px;
    margin: 12px 0;
}
.callout strong {
    display: block;
    margin-bottom: 5px;
}
.commands {
    margin-top: 12px;
    padding: 12px;
}
.commands h3 {
    margin: 0 0 8px;
    font-size: 15px;
}
.command {
    display: block;
    padding: 7px 8px;
    border-radius: 7px;
    background: color-mix(in srgb, var(--background-color-default, #fff) 92%, var(--true-color-blue, #0969da));
    margin: 6px 0;
    overflow-wrap: anywhere;
}
.legend {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 10px;
}
.legend span {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    color: var(--text-color-muted, #57606a);
    font-size: 12px;
}
.dot {
    width: 9px;
    height: 9px;
    border-radius: 999px;
    display: inline-block;
}
.source { background: var(--true-color-blue, #0969da); }
.task { background: var(--true-color-green, #1a7f37); }
.run { background: var(--true-color-purple, #8250df); }
.trial { background: var(--true-color-orange, #bc4c00); }
.analysis { background: var(--true-color-red, #cf222e); }
.derived { background: var(--true-color-yellow, #9a6700); }
.guidance { background: var(--text-color-muted, #57606a); }
.root { background: var(--text-color-default, #1f2328); }
@media (max-width: 980px) {
    .flow,
    .workspace {
        grid-template-columns: 1fr;
    }
    .flow-step:not(:last-child)::after {
        display: none;
    }
    .left {
        border-right: 0;
        border-bottom: 1px solid var(--border-color-default, #d0d7de);
        max-height: 58vh;
    }
    .meta {
        grid-template-columns: 1fr;
    }
}
</style>
</head>
<body>
<main>
<header>
    <h1>Experiment repository structure</h1>
    <p class="lede">A didactic map of a Pier-first copilot-experiments repo. New runs use <code>jobs/&lt;job-name&gt;/&lt;run-id&gt;/</code>, and <code>copilot-experiments list</code> prints the selectors accepted by <code>show</code>, <code>inspect</code>, and <code>analyze</code>.</p>
    <div class="legend" id="legend"></div>
</header>
<section class="flow" id="flow"></section>
<section class="workspace">
    <div class="left">
        <div class="controls">
            <input class="search" id="search" placeholder="Search paths, purpose, commands..." aria-label="Search structure" />
            <div class="chips" id="chips"></div>
        </div>
        <div class="tree" id="tree"></div>
    </div>
    <div class="right">
        <article class="detail" id="detail"></article>
    </div>
</section>
</main>
<script>
const STRUCTURE = ${data};
const FLOW = ${flowData};
const KINDS = ["all", "source", "task", "run", "trial", "analysis", "derived", "guidance"];
let selectedKind = "all";
let selectedId = "run-dir";
let query = "";

const byId = new Map(STRUCTURE.map(function(node) { return [node.id, node]; }));
const children = new Map();
for (const node of STRUCTURE) {
    const key = node.parent || "__root__";
    if (!children.has(key)) children.set(key, []);
    children.get(key).push(node);
}

function esc(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
}

function matches(node) {
    const haystack = [node.label, node.path, node.kind, node.badge, node.owner, node.source, node.why].concat(node.commands || []).join(" ").toLowerCase();
    const kindOk = selectedKind === "all" || node.kind === selectedKind;
    const queryOk = !query || haystack.includes(query.toLowerCase());
    return kindOk && queryOk;
}

function branchHasMatch(node) {
    if (matches(node)) return true;
    return (children.get(node.id) || []).some(branchHasMatch);
}

function renderFlow() {
    document.getElementById("flow").innerHTML = FLOW.map(function(step) {
        return '<div class="flow-step"><span class="flow-title">' + esc(step[0]) + '</span><span class="flow-path">' + esc(step[1]) + '</span></div>';
    }).join("");
}

function renderLegend() {
    const kinds = ["source", "task", "run", "trial", "analysis", "derived", "guidance"];
    document.getElementById("legend").innerHTML = kinds.map(function(kind) {
        return '<span><i class="dot ' + kind + '"></i>' + esc(kind) + '</span>';
    }).join("");
}

function renderChips() {
    document.getElementById("chips").innerHTML = KINDS.map(function(kind) {
        const active = kind === selectedKind ? " active" : "";
        return '<button class="chip' + active + '" data-kind="' + esc(kind) + '">' + esc(kind) + '</button>';
    }).join("");
    for (const button of document.querySelectorAll(".chip")) {
        button.addEventListener("click", function() {
            selectedKind = button.dataset.kind;
            render();
        });
    }
}

function renderTreeNode(node) {
    if (!branchHasMatch(node)) return "";
    const kids = children.get(node.id) || [];
    const selected = node.id === selectedId ? " selected" : "";
    const visibleKids = kids.map(renderTreeNode).join("");
    const twisty = kids.length ? "▾" : "";
    return '<div class="branch">' +
        '<button class="node' + selected + '" data-id="' + esc(node.id) + '">' +
        '<span class="twisty">' + twisty + '</span>' +
        '<span class="label"><span class="dot ' + esc(node.kind) + '"></span> <code>' + esc(node.label) + '</code></span>' +
        '<span class="badge">' + esc(node.badge) + '</span>' +
        '</button>' +
        (visibleKids ? '<div class="children">' + visibleKids + '</div>' : '') +
        '</div>';
}

function renderTree() {
    const roots = children.get("__root__") || [];
    document.getElementById("tree").innerHTML = roots.map(renderTreeNode).join("") || '<p class="lede">No matching nodes.</p>';
    for (const button of document.querySelectorAll(".node")) {
        button.addEventListener("click", function() {
            selectedId = button.dataset.id;
            renderDetail();
            renderTree();
        });
    }
}

function renderDetail() {
    const node = byId.get(selectedId) || STRUCTURE[0];
    const commands = (node.commands || []).length
        ? '<div class="commands"><h3>Useful command selectors</h3>' + node.commands.map(function(command) {
            return '<code class="command">' + esc(command) + '</code>';
        }).join("") + '</div>'
        : '<div class="commands"><h3>Useful command selectors</h3><span class="lede">No direct command; this node supports nearby run or analysis commands.</span></div>';
    document.getElementById("detail").innerHTML =
        '<h2>' + esc(node.label) + '</h2>' +
        '<code class="path">' + esc(node.path) + '</code>' +
        '<div class="meta">' +
        '<div class="meta-card"><strong>Category</strong><span>' + esc(node.kind) + '</span></div>' +
        '<div class="meta-card"><strong>Owner</strong><span>' + esc(node.owner) + '</span></div>' +
        '<div class="meta-card"><strong>Status</strong><span>' + esc(node.badge) + '</span></div>' +
        '</div>' +
        '<div class="callout"><strong>What it is</strong>' + esc(node.source) + '</div>' +
        '<div class="callout"><strong>Why it exists</strong>' + esc(node.why) + '</div>' +
        commands;
}

function render() {
    renderChips();
    renderTree();
    renderDetail();
}

document.getElementById("search").addEventListener("input", function(event) {
    query = event.target.value;
    renderTree();
});

renderFlow();
renderLegend();
render();
</script>
</body>
</html>`;
}

async function startServer(instanceId) {
    const server = createServer((req, res) => {
        if (req.url === "/structure.json") {
            res.setHeader("Content-Type", "application/json; charset=utf-8");
            res.end(JSON.stringify({ structure, flow }));
            return;
        }

        res.setHeader("Content-Type", "text/html; charset=utf-8");
        res.end(renderHtml(instanceId));
    });
    await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    const port = typeof address === "object" && address ? address.port : 0;
    return { server, url: `http://127.0.0.1:${port}/` };
}

await joinSession({
    canvases: [
        createCanvas({
            id: "experiment-repository-structure",
            displayName: "Experiment repository structure",
            description: "Interactive didactic map of a Pier-first copilot-experiments repository layout.",
            actions: [
                {
                    name: "summarize",
                    description: "Return a concise summary of the experiment repository structure.",
                    handler: async () => ({
                        layout: "Pier runs live at jobs/<job-name>/<run-id>/.",
                        selector: "Use copilot-experiments list, then pass job-name/run-id to show, inspect, or analyze.",
                        sourceOfTruth: "jobs/<job-name>/<run-id>/ on disk; summaries are derived.",
                        nodes: structure.length,
                    }),
                },
            ],
            open: async (ctx) => {
                let entry = servers.get(ctx.instanceId);
                if (!entry) {
                    entry = await startServer(ctx.instanceId);
                    servers.set(ctx.instanceId, entry);
                }
                return {
                    title: "Experiment repository structure",
                    status: "Pier-first layout with copyable run selectors",
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
