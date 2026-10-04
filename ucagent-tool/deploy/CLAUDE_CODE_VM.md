
# Claude Code on the EDA VM

The installed CLI is `2.1.263`, running as `ucagent` with a private musl runtime.
The EDA operating system and its libraries remain unchanged. This compatibility
deployment passed CLI startup on CentOS 7 but is not an officially supported OS.
The authoritative installation requirements and gateway setup are documented by
[Claude Code](https://code.claude.com/docs/en/setup) and its
[gateway connection guide](https://code.claude.com/docs/en/llm-gateway-connect).

## Launch

From an administrator SSH session, use the non-root execution identity:

```bash
su - ucagent
claude --version
claude --model gpt-5.6-sol
```

The launcher resolves to
`/home/ucagent-lab/tools/claude-code/2.1.263/bin/claude`. Neither Node nor a system
glibc upgrade is required by this installation. Do not invoke `claude update`;
updates are pinned off and a new version must pass the compatibility checks.

The user's approved gateway model is `gpt-5.6-sol`, also saved as the default for
new sessions. The CLI remains Claude Code; the requested and gateway-reported
model is GPT, not an Anthropic Claude model. This is third-party compatibility,
not vendor-supported parity across every Claude Code feature.

Interactive coding grants different capabilities from the platform's automated
restricted requests; do not approve access to credentials, license files or
commercial SDK/library contents. The gateway receives the prompts and selected
engineering content sent by the CLI.

## Gateway configuration and rotation

Only the host user owns the gateway configuration:
`/home/ucagent-lab/home/.claude/settings.json` (0600; parent directory 0700).
Do not copy it into a project, release bundle, issue, log or database. Do not
display the entire settings file while troubleshooting.

Configure or replace the credential using the no-echo prompt, as `ucagent`:

```bash
cd /home/ucagent-lab/development/20260906-design-dv-r1
/home/ucagent-lab/current/venv/bin/python deploy/configure_claude_provider.py \
  --base-url https://shanyiapi.com --list-models
```

The credential is sent in the `Authorization: Bearer` header. The gateway origin
is stored as `ANTHROPIC_BASE_URL`, and nonessential telemetry/update traffic is
disabled. Model discovery does not forward authentication through redirects.
To select an explicitly approved, actually available model without retyping the
credential, add `--use-stored-credential --model <exact-model-id>`. The literal
model ID is added as a clearly named custom model option. No Claude alias is
renamed to disguise a GPT model, and no fallback model is configured. Claude-only
features, built-in model aliases and model-specific background functions must
not be assumed compatible merely because normal model and MCP calls work.

## Current acceptance state

On 2026-09-06 the user explicitly approved GPT-model access through Claude Code.
The gateway accepts the CLI protocol directly; no local translation proxy was
installed. Real requests using `gpt-5.6-sol` passed these bounded checks:

- A new session returned a random session marker exactly.
- A second invocation resumed the explicit UUID and retrieved that marker.
- A real MCP read retrieved a different random marker from an approved synthetic
  file; both CLI tool-use events and server-side calls were checked.
- A request to a deliberately unapproved, harmless canary tool was denied; its
  server-side implementation was not executed.
- The requested model, startup model and reported model usage agree. Explicit
  `--model` pinning also applies on resume; a mismatch fails the parser.

These checks do not expose engineering data or Shell tools. CLI calls remain
`verification_status=unknown`: model execution is not design verification. The
permission-negative job intentionally has execution status `error`, which is the
expected evidence of denial, not a failed compatibility test.

Signed evidence is retained in `acceptance/claude-gpt-2` and
`acceptance/claude-gpt-mcp-2` under the VM development source. The MCP acceptance
server is a loopback-only synthetic fixture, **not** acceptance of the complete
production Campaign MCP service. The full Campaign/ISP/PPA platform still has
separate implementation and release gates. Earlier Claude-model 503/timeout
evidence remains unchanged and is not relabeled as a pass.

Token usage and model names are gateway/CLI-reported data. The CLI reports an
unknown pricing basis for this custom model; its displayed USD estimate is not
a verified gateway bill or a reliable financial budget gate. The gateway's
account billing is authoritative. Long-context, compaction, model-specific
reasoning and all interactive subcommands have not been comprehensively tested.

## Reproducible checks

`deploy/install_claude_musl.py` checks the pinned archive integrity before
extracting an explicit file allowlist into a new version directory. Installation
hashes are retained on the host. It never runs an archive-provided install script.

`deploy/claude_vm_smoke.py` uses the existing JobRunner for version/help, a
minimal gateway prompt, and an exact-UUID resume test. Use a **new** relative
output path on every invocation; do not overwrite prior evidence:

```bash
PYTHONPATH=/home/ucagent-lab/development/20260906-design-dv-r1 \
/home/ucagent-lab/current/venv/bin/python deploy/claude_vm_smoke.py \
  --output acceptance/claude-gateway-next --mode resume
```

This command uses the configured gateway and can incur token charges. It sends
only a generated session marker, not an engineering project. CLI execution
success still leaves engineering verification status `unknown`.

Use `deploy/claude_mcp_smoke.py --output <new-relative-directory>` to repeat the
MCP positive and permission-negative checks. It starts an ephemeral loopback
server in-process and stops it after the CLI jobs, retaining signed results and
server-side call evidence. No production MCP server or service is replaced.
