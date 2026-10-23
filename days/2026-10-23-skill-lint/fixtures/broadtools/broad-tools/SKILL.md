---
name: broad-tools
description: Deploys the site. Use when the user says deploy.
allowed-tools: Bash Bash(python3 *) Bash(git status:*) Read
hooks:
  PreToolUse:
    - matcher: Bash
---

body
