#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
share_root="${OLLAMA_CONTROL_TOWER_HOME:-$HOME/.local/share/ollama-control-tower}"
bin_root="${OLLAMA_CONTROL_TOWER_BIN:-$HOME/.local/bin}"
canonical_python="/home/praveen/venv-ardupilot/bin/python"

if [[ ! -x "$canonical_python" ]]; then
  echo "canonical Python is unavailable: $canonical_python" >&2
  exit 1
fi

install -d -m 755 "$share_root/config" "$share_root/docs" "$share_root/scripts" "$share_root/portal" "$share_root/systemd" "$bin_root"
# Publish only committed artifacts. Other projects may be editing this shared
# checkout, and their unstaged code must never leak into the global install.
git -C "$repo_root" archive HEAD config docs scripts portal systemd README.md CLAUDE.md requirements.txt | tar -x -C "$share_root"

cat > "$bin_root/control-tower" <<EOF
#!/usr/bin/env bash
set -euo pipefail
source /home/praveen/venv-ardupilot/bin/activate
exec "$share_root/scripts/control-tower" "\$@"
EOF
chmod 755 "$bin_root/control-tower"

cat > "$share_root/INSTALLATION.json" <<EOF
{
  "source": "$repo_root",
  "git_commit": "$(git -C "$repo_root" rev-parse HEAD)",
  "python": "$canonical_python",
  "launcher": "$bin_root/control-tower"
}
EOF
chmod 644 "$share_root/INSTALLATION.json"

echo "Installed Ollama Control Tower at $share_root"
echo "Global command: $bin_root/control-tower"
