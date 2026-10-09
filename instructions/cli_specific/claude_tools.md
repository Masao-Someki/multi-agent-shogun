# Claude Code Tools

This section describes Claude Code-specific tools and features.

## Tool Usage

Claude Code provides specialized tools for file operations, code execution, and system interaction:

- **Read**: Read files from the filesystem (supports images, PDFs, Jupyter notebooks)
- **Write**: Create new files or overwrite existing files
- **Edit**: Perform exact string replacements in files
- **Bash**: Execute bash commands with timeout control
- **Glob**: Fast file pattern matching with glob patterns
- **Grep**: Content search using ripgrep
- **Task**: Launch specialized agents for complex multi-step tasks
- **WebFetch**: Fetch and process web content
- **WebSearch**: Search the web for information

## Tool Guidelines

1. **Read before Write/Edit**: Always read a file before writing or editing it
2. **Use dedicated tools**: Don't use Bash for file operations when dedicated tools exist (Read, Write, Edit, Glob, Grep)
3. **Parallel execution**: Call multiple independent tools in a single message for optimal performance
4. **Avoid over-engineering**: Only make changes that are directly requested or clearly necessary

## Task Tool Usage

The Task tool launches specialized agents for complex work:

- **Explore**: Fast agent specialized for codebase exploration
- **Plan**: Software architect agent for designing implementation plans
- **general-purpose**: For researching complex questions and multi-step tasks
- **Bash**: Command execution specialist

Use Task tool when:
- You need to explore the codebase thoroughly (medium or very thorough)
- Complex multi-step tasks require autonomous handling
- You need to plan implementation strategy

## Memory (file-based)

Memory MCP (`mcp__memory__*`, server-memory backend) was **retired 2026-07-01** — never call it.
Persistent memory is file-based: `memory/MEMORY.md` is the always-loaded index (shogun only),
with one fact per individual memory file (`feedback_*.md` / `project_*.md` / `reference_*.md` / `user_*.md`).

To save: write/update the individual file (include Why + How to apply), then add a one-line
pointer to `MEMORY.md`. Update existing files rather than duplicating; delete memories proven wrong.

Use for: Lord's preferences, key decisions + reasons, cross-project insights, solved problems.

Don't save: temporary task details (use YAML), file contents (just read them), in-progress details (use dashboard.md).

## Model Switching

Ashigaru models are set in `config/settings.yaml` and applied at startup.
Runtime switching is available but rarely needed (Gunshi handles L4+ tasks instead):

```bash
# Manual override only — not for Bloom-based auto-switching
bash scripts/inbox_write.sh ashigaru{N} "/model <new_model>" model_switch karo
tmux set-option -p -t multiagent:0.{N} @model_name '<DisplayName>'
```

For Ashigaru: You don't switch models yourself. Karo manages this.

## /clear Protocol

For Karo only: Send `/clear` to ashigaru for context reset:

```bash
bash scripts/inbox_write.sh ashigaru{N} "Read your task YAML and start the work." clear_command karo
```

For Ashigaru: After `/clear`, follow CLAUDE.md /clear recovery procedure. Do NOT read instructions/ashigaru.md for the first task (cost saving).

## Compaction Recovery

All agents: Follow the Session Start / Recovery procedure in CLAUDE.md. Key steps:

1. Identify self: `tmux display-message -t "$TMUX_PANE" -p '#{@agent_id}'`
2. (shogun only) Read `memory/MEMORY.md` — restore rules, preferences, lessons (file-based memory)
3. Read your instructions file (shogun→instructions/shogun.md, karo→instructions/karo.md, ashigaru→instructions/ashigaru.md)
4. Rebuild state from primary YAML data (queue/, tasks/, reports/)
5. Review forbidden actions, then start work
