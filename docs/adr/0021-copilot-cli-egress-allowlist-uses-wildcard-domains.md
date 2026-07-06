# 0021. The copilot-cli egress allowlist uses dotted-wildcard domains only

- **Status:** Accepted
- **Date:** 2026-07-06
- **Deciders:** project owner, Copilot

## Context

The local `copilot-cli` Pier installed agent (`src/copilot_experiments/pier_agents/copilot_cli.py`)
declares a `NetworkAllowlist` so air-gapped DeepSWE tasks (`allow_internet = false`) can still reach
the small set of GitHub hosts the Copilot CLI needs to install and run.

Pier enforces that allowlist with an **egress proxy that is a Squid instance**. Squid renders the
allowlist into a `dstdomain` ACL, one entry per domain. Squid's `dstdomain` treats a bare domain and
its leading-dot wildcard as an **overlapping, fatal** pair: if both `github.com` and `.github.com`
appear, Squid aborts at startup with

```
ERROR: '.github.com' is a subdomain of 'github.com'
FATAL: Bungled ... acl allowed_domains dstdomain
```

The proxy container exits (1). The agent (`main`) container depends on the proxy via
`condition: service_healthy`, so every trial fails to start its environment. Pier then surfaces a
confusing downstream symptom — `Could not find the file /logs/artifacts/model.patch` — that hides the
real cause. The original allowlist listed three domains both bare and dotted
(`github.com`/`.github.com`, `githubcopilot.com`/`.githubcopilot.com`,
`githubusercontent.com`/`.githubusercontent.com`), so this crashed 100% of DeepSWE trials.

## Decision

We will list **only** the leading-dot wildcard form for any domain whose subdomains we need. In
Squid a `.example.com` entry already matches the apex `example.com` *and* every subdomain, so the
bare entries are both redundant and fatal. The allowlist is:

```python
[".github.com", ".githubcopilot.com", ".githubusercontent.com", "gh.io"]
```

`gh.io` stays bare: it is a single redirector host with no subdomains we call, and its
`/copilot-install` redirect targets `*.githubusercontent.com`, already covered by the wildcard.

A regression test asserts the wildcard domains are present and that no domain appears both bare and
as a `.domain` wildcard, so this exact Squid conflict cannot be reintroduced silently.

## Consequences

- DeepSWE (and any other air-gapped) tasks run through the egress proxy again; the proxy container
  starts healthy instead of exiting (1).
- Anyone extending the allowlist must add the **dotted** form (e.g. `.example.com`), not the bare
  domain, whenever subdomains are needed — the test enforces this and a code comment explains why.
- Bare domains remain acceptable only for hosts with no subdomain we contact (like `gh.io`); if such
  a host ever needs subdomains, switch it to the dotted form rather than listing both.
