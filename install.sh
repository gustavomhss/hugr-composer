#!/usr/bin/env bash
# HuGR Skills installer — one-command setup for Claude Code / Cursor / Windsurf.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/humangr-labs/HuGR_Skills/main/install.sh | bash
#   curl -fsSL .../install.sh | SKILL=fastapi-production bash
#
# Environment variables:
#   INSTALL_DIR   Where to clone the repo (default: ~/.hugr-skills)
#   SKILL         Which skill to install (default: fastapi-production)
#   SHELL_RC      Shell rc file to patch (default: auto-detect from $SHELL)
#
# What this script does:
#   1. Clones HuGR_Skills into INSTALL_DIR (or pulls if already present)
#   2. Creates a Python venv under {INSTALL_DIR}/{SKILL}/.venv
#   3. Installs the skill's requirements-mcp.txt
#   4. Prints the exact .mcp.json stanza to add to Claude Code / Cursor

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/humangr-labs/HuGR_Skills.git}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.hugr-skills}"
SKILL="${SKILL:-fastapi-production}"
SKILL_DIR="${INSTALL_DIR}/skills/SKILL-001-${SKILL}"

# ---------------------------------------------------------------------------
# Pretty output helpers
# ---------------------------------------------------------------------------

c_reset='\033[0m'
c_bold='\033[1m'
c_green='\033[32m'
c_cyan='\033[36m'
c_yellow='\033[33m'
c_red='\033[31m'

log()   { printf "${c_cyan}→${c_reset} %s\n" "$*"; }
ok()    { printf "${c_green}✓${c_reset} %s\n" "$*"; }
warn()  { printf "${c_yellow}!${c_reset} %s\n" "$*"; }
die()   { printf "${c_red}✗${c_reset} %s\n" "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

command -v git    >/dev/null 2>&1 || die "git is required but not installed"
command -v python3 >/dev/null 2>&1 || die "python3 is required but not installed"

PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 12 ]; }; then
  die "Python 3.12+ required, found $PY_VER"
fi
ok "Python $PY_VER"

# ---------------------------------------------------------------------------
# Clone or update
# ---------------------------------------------------------------------------

if [ -d "${INSTALL_DIR}/.git" ]; then
  log "Updating existing installation at ${INSTALL_DIR}"
  git -C "${INSTALL_DIR}" pull --ff-only --quiet || warn "git pull failed, continuing with existing copy"
else
  log "Cloning ${REPO_URL} → ${INSTALL_DIR}"
  git clone --depth 1 --quiet "${REPO_URL}" "${INSTALL_DIR}"
fi
ok "Repo ready at ${INSTALL_DIR}"

[ -d "${SKILL_DIR}" ] || die "Skill directory not found: ${SKILL_DIR}"

# ---------------------------------------------------------------------------
# Create venv + install deps
# ---------------------------------------------------------------------------

VENV="${SKILL_DIR}/.venv"
if [ ! -d "${VENV}" ]; then
  log "Creating virtualenv at ${VENV}"
  python3 -m venv "${VENV}"
fi

log "Installing skill dependencies (this may take a minute)"
"${VENV}/bin/pip" install --upgrade --quiet pip
if [ -f "${SKILL_DIR}/requirements-mcp.txt" ]; then
  "${VENV}/bin/pip" install --quiet -r "${SKILL_DIR}/requirements-mcp.txt"
else
  warn "No requirements-mcp.txt found — skipping dependency install"
fi
ok "Dependencies installed"

# ---------------------------------------------------------------------------
# Print the .mcp.json stanza the user needs to paste
# ---------------------------------------------------------------------------

MCP_SERVER_PATH="${SKILL_DIR}/mcp_server.py"
PY_PATH="${VENV}/bin/python"

cat <<EOF

${c_bold}${c_green}✓ HuGR Skills installed successfully${c_reset}

Add this to your ${c_bold}.mcp.json${c_reset} (Claude Code) or ${c_bold}MCP settings${c_reset} (Cursor/Windsurf):

${c_cyan}{
  "mcpServers": {
    "fastapi-production": {
      "command": "${PY_PATH}",
      "args": ["${MCP_SERVER_PATH}"],
      "env": {
        "PYTHONPATH": "${SKILL_DIR}"
      }
    }
  }
}${c_reset}

After adding the stanza, restart your IDE.  The skill exposes ${c_bold}100 MCP tools${c_reset}
for generating production-grade FastAPI projects:

  fastapi_generate_project      — one call → 53-file production API
  fastapi_add_rbac              — add role-based access control
  fastapi_add_mfa               — add TOTP two-factor auth
  fastapi_add_audit_log         — add tamper-evident audit trail
  fastapi_add_soft_delete       — add is_deleted flag + restore endpoint
  ...and 95 more

${c_bold}Quick test:${c_reset}
  ${PY_PATH} ${MCP_SERVER_PATH} --list-tools

${c_bold}Full docs:${c_reset}
  ${SKILL_DIR}/SKILL.md
  ${SKILL_DIR}/README.md

EOF
