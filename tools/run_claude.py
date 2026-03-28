"""Run Claude CLI with all project rules injected as system prompt context.

Collects all .cursor/rules/*.mdc files and AGENTS.md from the workspace root,
concatenates them into a context file, then launches Claude CLI with
--append-system-prompt-file so Claude has full project rules without relying
on CLAUDE.md @-imports (which Claude CLI doesn't process).

Image files are appended as file-path references in the prompt text. Claude CLI
reads them directly via its built-in Read tool (--dangerously-skip-permissions
allows access to any path). Note: --input-format stream-json silently drops all
input in the current Claude CLI version, so we use plain text piping only.

Usage (via Bazel):
    bazel run //tools:run_claude -- --model sonnet --prompt-file /tmp/claude_prompt.txt
    bazel run //tools:run_claude -- --model opus --prompt-file /tmp/claude_prompt.txt
    bazel run //tools:run_claude -- --model sonnet --plan --prompt-file /tmp/claude_prompt.txt
    bazel run //tools:run_claude -- --model sonnet --prompt-file /tmp/claude_prompt.txt --image-file /tmp/shot.png
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def find_workspace() -> Path:
    """Find project root via BUILD_WORKSPACE_DIRECTORY (set by bazel run)."""
    env_dir = os.environ.get("BUILD_WORKSPACE_DIRECTORY")
    if env_dir:
        return Path(env_dir)
    path = Path(__file__).resolve()
    for parent in path.parents:
        if (parent / "MODULE.bazel").exists() or (parent / "WORKSPACE").exists():
            return parent
    return Path.cwd()


def _rule_content(rule_file: Path, display_name: str) -> "str | None":
    """Read a rule file, strip YAML frontmatter, return formatted section or None if empty."""
    content = rule_file.read_text().strip()
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            content = content[end + 3:].lstrip()
    if not content:
        return None
    return f"# === {display_name} ===\n\n{content}"


def collect_rules(workspace: Path) -> str:
    """Concatenate AGENTS.md + all .cursor/rules/*.mdc + ~/.cursor/shared_rules/*.mdc.

    Deduplicates by resolved real path so symlinked shared rules aren't included twice
    (project rules link to shared_rules/, but shared_rules/ is also scanned directly).
    """
    parts = []

    agents_file = workspace / "AGENTS.md"
    if agents_file.exists():
        parts.append(f"# === AGENTS.md ===\n\n{agents_file.read_text()}")

    seen_real_paths: set[Path] = set()

    # Project rules first (includes symlinks pointing into shared_rules/)
    rules_dir = workspace / ".cursor" / "rules"
    if rules_dir.exists():
        for rule_file in sorted(rules_dir.glob("*.mdc")):
            seen_real_paths.add(rule_file.resolve())
            section = _rule_content(rule_file, rule_file.name)
            if section:
                parts.append(section)

    # Shared rules — skip any already included via project symlinks
    shared_dir = Path.home() / ".cursor" / "shared_rules"
    if shared_dir.exists():
        for rule_file in sorted(shared_dir.glob("*.mdc")):
            if rule_file.resolve() in seen_real_paths:
                continue
            section = _rule_content(rule_file, rule_file.name)
            if section:
                parts.append(section)

    return "\n\n".join(parts)


def _format_tool_call(name: str, inp: dict) -> str:
    """Format a tool_use block for human display."""
    if name in ("Bash", "bash", "execute_bash"):
        cmd = inp.get("command", inp.get("cmd", ""))
        desc = inp.get("description", "")
        header = "▶ Bash" + (f"  [{desc}]" if desc else "")
        if cmd:
            cmd_lines = "\n".join(f"  $ {line}" for line in cmd.splitlines() if line.strip())
            return f"\n{header}\n{cmd_lines}\n"
        return f"\n{header}\n"

    if name in ("Write", "write_file", "create_file"):
        path = inp.get("file_path", inp.get("path", inp.get("file_name", "?")))
        return f"\n▶ Write  {path}\n"

    if name in ("Read", "read_file"):
        path = inp.get("file_path", inp.get("path", "?"))
        return f"\n▶ Read   {path}\n"

    if name in ("str_replace_editor", "StrReplace", "str_replace", "EditFile"):
        path = inp.get("path", inp.get("file_path", "?"))
        cmd = inp.get("command", "edit")
        return f"\n▶ Edit ({cmd})  {path}\n"

    if name in ("Glob", "glob"):
        pattern = inp.get("pattern", inp.get("glob_pattern", "?"))
        return f"\n▶ Glob  {pattern}\n"

    if name in ("Grep", "grep"):
        pattern = inp.get("pattern", "?")
        path = inp.get("path", inp.get("directory", ""))
        loc = f"  in {path}" if path else ""
        return f"\n▶ Grep  {pattern!r}{loc}\n"

    if name in ("TodoWrite", "todo_write", "TodoRead", "todo_read"):
        return f"\n▶ {name}\n"

    # Generic fallback — skip large content fields, show key params
    skip_keys = {"content", "new_string", "old_string", "new_content"}
    short_inp = {k: v for k, v in inp.items() if k not in skip_keys}
    summary = json.dumps(short_inp, ensure_ascii=False)
    if len(summary) > 300:
        summary = summary[:300] + "…"
    return f"\n▶ {name}  {summary}\n"


def _format_tool_result(block: dict) -> "str | None":
    """Format a tool_result block (command output) for display."""
    content = block.get("content", "")
    if isinstance(content, list):
        text_parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        content = "\n".join(text_parts)
    if not content or not isinstance(content, str):
        return None
    content = content.strip()
    if not content:
        return None

    lines = content.splitlines()
    max_lines = 40
    if len(lines) > max_lines:
        keep_head, keep_tail = 10, 28
        omitted = len(lines) - keep_head - keep_tail  # noqa: SIM117
        shown = lines[:keep_head] + [f"  … ({omitted} lines omitted) …"] + lines[-keep_tail:]
    else:
        shown = lines

    result_text = "\n".join(f"  {line}" for line in shown)
    return f"  ↳ {result_text}\n"


def filter_stream(line: str) -> "str | None":
    """Convert a Claude CLI stream-json line to a human-readable string, or None to skip."""
    line = line.strip()
    if not line:
        return None
    try:
        d = json.loads(line)
    except json.JSONDecodeError:
        return None

    t = d.get("type", "")

    if t == "system":
        sub = d.get("subtype", "")
        if sub == "init":
            model = d.get("model", "?")
            return f"[Claude {model}] Session started\n"
        if sub == "task_progress":
            desc = d.get("description", "")
            return f"  … {desc}\n" if desc else None
        if sub == "task_notification":
            summary = d.get("summary", "")
            usage = d.get("usage", {})
            tools = usage.get("tool_uses", 0)
            ms = usage.get("duration_ms", 0)
            return f"  [Agent done] {summary} ({tools} tools, {ms}ms)\n"
        return None

    if t == "assistant":
        msg = d.get("message", {})
        parts = []
        for block in msg.get("content", []):
            if block.get("type") == "tool_use":
                parts.append(_format_tool_call(block.get("name", "?"), block.get("input", {})))
        return "".join(parts) or None

    if t == "user":
        # Tool results — show bash/shell output; skip silent results from Write/Read
        msg = d.get("message", {})
        parts = []
        for block in msg.get("content", []):
            if isinstance(block, dict) and block.get("type") == "tool_result":
                formatted = _format_tool_result(block)
                if formatted:
                    parts.append(formatted)
        return "".join(parts) or None

    if t == "stream_event":
        ev = d.get("event", {})
        if ev.get("type") == "content_block_delta":
            delta = ev.get("delta", {})
            if delta.get("type") == "text_delta":
                return delta.get("text", "")
        return None

    if t == "result":
        subtype = d.get("subtype", "")
        duration = d.get("duration_ms", 0)
        cost = d.get("total_cost_usd", 0)
        turns = d.get("num_turns", 0)
        result = f"\n\n--- Done ({turns} turns, {duration / 1000:.1f}s, ${cost:.4f}) ---\n"
        if subtype != "success":
            err = d.get("result", "")
            result += f"ERROR: {err}\n"
        return result

    return None


def find_claude() -> str:
    """Return path to claude CLI, or exit with an error."""
    candidate = os.path.expanduser("~/.local/bin/claude")
    if os.path.exists(candidate):
        return candidate
    found = shutil.which("claude")
    if found:
        return found
    print(
        "ERROR: claude CLI not found. Install with: curl -fsSL https://claude.ai/install.sh | bash",
        file=sys.stderr,
    )
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Claude CLI with project rules injected.")
    parser.add_argument("--model", choices=["sonnet", "opus"], default="sonnet")
    parser.add_argument("--plan", action="store_true", help="Enable planning mode (read-only).")
    parser.add_argument("--prompt-file", required=True, help="Path to file containing the prompt.")
    parser.add_argument(
        "--image-file",
        action="append",
        dest="image_files",
        default=[],
        metavar="PATH",
        help="Image file for Claude to read (can be repeated). Claude CLI reads it via its Read tool.",
    )
    args = parser.parse_args()

    workspace = find_workspace()

    # Build rules context file
    context = collect_rules(workspace)
    context_file = Path("/tmp/claude_rules_context.txt")
    context_file.write_text(context)

    # Read prompt
    prompt_path = Path(args.prompt_file)
    if not prompt_path.exists():
        print(f"ERROR: prompt file not found: {prompt_path}", file=sys.stderr)
        sys.exit(1)
    prompt = prompt_path.read_text()

    # Append image file references to prompt text so Claude CLI reads them via its Read tool
    image_files = [Path(p) for p in args.image_files]
    for img in image_files:
        if not img.exists():
            print(f"ERROR: image file not found: {img}", file=sys.stderr)
            sys.exit(1)
    if image_files:
        img_refs = "\n".join(f"  - {img}" for img in image_files)
        prompt = prompt + f"\n\nThe following image file(s) are attached — read each one:\n{img_refs}"

    # Log file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    label = "plan" if args.plan else args.model
    log_file = Path(f"/tmp/claude_{label}_{timestamp}.log")

    claude_path = find_claude()

    cmd = [
        claude_path,
        "-p",
        "--model", args.model,
        "--dangerously-skip-permissions",
        "--append-system-prompt-file", str(context_file),
        "--output-format", "stream-json",
        "--include-partial-messages",
        "--verbose",
    ]
    if args.plan:
        cmd += ["--permission-mode", "plan"]

    if image_files:
        img_names = ", ".join(img.name for img in image_files)
        print(f"[run_claude] images: {img_names}", flush=True)
    print(f"[run_claude] model={args.model} plan={args.plan} log={log_file}", flush=True)
    project_rules = list((workspace / ".cursor" / "rules").glob("*.mdc"))
    shared_rules = list((Path.home() / ".cursor" / "shared_rules").glob("*.mdc")) if (Path.home() / ".cursor" / "shared_rules").exists() else []
    num_rules = len(project_rules) + len(shared_rules)
    print(f"[run_claude] rules: {len(context)} chars ({num_rules} files, {len(project_rules)} project + {len(shared_rules)} shared)", flush=True)
    print("", flush=True)

    # In plan mode, also capture clean markdown to a separate .md file
    plan_file = None
    plan_fh = None
    if args.plan:
        plan_file = Path(f"/tmp/claude_plan_{timestamp}.md")
        plan_fh = open(plan_file, "w")
        # Symlink for easy access
        latest = Path("/tmp/claude_plan_latest.md")
        latest.unlink(missing_ok=True)
        latest.symlink_to(plan_file)
        print(f"[run_claude] plan file: {plan_file}", flush=True)
        print("[run_claude] plan symlink: /tmp/claude_plan_latest.md", flush=True)
        print("", flush=True)

    with open(log_file, "w") as log_fh:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(workspace),
        )
        proc.stdin.write(prompt)
        proc.stdin.close()

        for raw_line in proc.stdout:
            log_fh.write(raw_line)
            log_fh.flush()
            out = filter_stream(raw_line)
            if out is not None:
                sys.stdout.write(out)
                sys.stdout.flush()
                # Write only text content to plan file (skip tool calls, status lines, --- lines)
                if plan_fh and not out.startswith(("\n▶ ", "[Claude ", "  … ", "  ↳ ", "  [Agent", "\n\n--- Done")):
                    plan_fh.write(out)
                    plan_fh.flush()

        proc.wait()

    if plan_fh:
        plan_fh.close()

    print(f"\n[run_claude] log saved to {log_file}", flush=True)
    if plan_file:
        print(f"[run_claude] plan saved to {plan_file}", flush=True)
        print("[run_claude] also at /tmp/claude_plan_latest.md", flush=True)
    sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
