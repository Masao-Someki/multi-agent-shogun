# Cursor Agent CLI — Tool-Specific Rules

These rules apply only in the Cursor Agent CLI environment.
Use them together with the shared protocol (CLAUDE.md / AGENTS.md) and the role instructions.

## Overview

- `CLAUDE.md`, `AGENTS.md` and `.cursor/rules/` are loaded automatically at session start
- The CLI starts in `--yolo` mode (Auto-run), so tool runs need no extra approval
- Agents talk to each other through the `inbox-write` skill

## Session reset

```
/new-chat
```

## Exit

```
/quit
```

(The text and Enter are sent 0.3s apart.)

## Agent-to-agent messages

Always use the `inbox-write` skill to send a message to an agent.
Never drive tmux directly.

```bash
bash scripts/inbox_write.sh <target_agent> "<message>" <type> <from>
```

## Switching models

```
/model <model-name>
```

Run it with no argument to list the available models.

## Files loaded automatically

| File | Contents |
|------|----------|
| `CLAUDE.md` | Session steps, communication protocol, forbidden actions |
| `AGENTS.md` | Agent layout |
| `.cursor/rules/` | Extra rules (Always Apply type) |
| `.cursor/skills/` | Skill definitions (loaded at startup) |

## Available tools

Cursor Agent provides these tools:

- **File operations**: read, write, edit
- **Shell commands**: run terminal commands
- **Web search**: built-in search
