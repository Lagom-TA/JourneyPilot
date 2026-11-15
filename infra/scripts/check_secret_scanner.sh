#!/usr/bin/env bash
# 使用已安装的扫描器和仓库规则，确认合成密钥仍会被检出。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fixture_dir="$(mktemp -d)"
trap 'rm -rf "$fixture_dir"' EXIT

# 运行时拼接，避免自检样本进入 git 历史扫描；不对应任何真实凭据。
key="AK""IA""EYKH2CMZ5ML24UMD"
printf 'aws_access_key_id = "%s"\n' "$key" > "$fixture_dir/planted-secret.txt"

# 单独约定检出时的退出码，执行失败与未检出都不能算自检成功。
status=0
gitleaks detect --source "$fixture_dir" --no-git --config "$ROOT/.gitleaks.toml" \
  --redact --exit-code=42 --report-format=json --report-path "$fixture_dir/report.json" \
  || status=$?
if [[ "$status" != 42 ]]; then
  printf 'Scanner self-check failed: expected detection exit code 42, got %s\n' "$status" >&2
  exit 1
fi

python3 - "$fixture_dir/report.json" <<'PY'
import json
import sys
from pathlib import Path

findings = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if not any(
    finding.get("RuleID") == "aws-access-token"
    and Path(finding.get("File", "")).name == "planted-secret.txt"
    for finding in findings
):
    raise SystemExit("Scanner self-check failed: planted AWS key missing from report")
print("Scanner self-check passed: planted AWS key detected")
PY
