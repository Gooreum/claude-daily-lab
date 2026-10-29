#!/usr/bin/env bash
# test.sh — sandbox_lint.py 단위 테스트. 키·모델 없이 돈다. 이 폴더에서 `bash test.sh`.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
HERE="$(pwd)"
L="python3 -I $HERE/sandbox_lint.py"
pass=0; fail=0
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
H="$T/home"; P="$T/proj"

expect() { # $1=label $2=기대 종료코드 $3=출력에 있어야 할 문자열 $4=있으면 안 되는 문자열 ; 나머지=명령
  local label="$1" want="$2" needle="$3" absent="$4"; shift 4
  local out rc; out="$("$@" 2>&1)"; rc=$?
  if [ "$rc" -eq "$want" ] && { [ -z "$needle" ] || [[ "$out" == *"$needle"* ]]; } && { [ -z "$absent" ] || [[ "$out" != *"$absent"* ]]; }; then
    pass=$((pass+1)); echo "  ✅ $label (exit=$rc)"
  else
    fail=$((fail+1)); echo "  ❌ $label (exit=$rc, expected $want, needle='$needle', absent='$absent')"; echo "$out" | sed 's/^/      /'
  fi
}
mk() { rm -rf "$H" "$P"; mkdir -p "$H/.claude" "$P/.claude"; }
user() { printf '%s' "$1" > "$H/.claude/settings.json"; }
proj() { printf '%s' "$1" > "$P/.claude/settings.json"; }
loc()  { printf '%s' "$1" > "$P/.claude/settings.local.json"; }
run()  { $L "$P" --home "$H" --no-managed "$@"; }

# 무인 작업 기준을 모두 만족하는 사용자 설정
GOOD='{"sandbox":{"enabled":true,"failIfUnavailable":true,"allowUnsandboxedCommands":false,
 "network":{"strictAllowlist":true,"allowedDomains":["registry.npmjs.org","pypi.org"]},
 "credentials":{"files":[{"path":"~/.ssh","mode":"deny"},{"path":"~/.aws","mode":"deny"},{"path":"~/.gnupg","mode":"deny"},
   {"path":"~/.kube","mode":"deny"},{"path":"~/.config/gh","mode":"deny"},{"path":"~/.netrc","mode":"deny"},{"path":"~/.npmrc","mode":"deny"}]}},
 "permissions":{"deny":["Read(~/.ssh/**)","Read(~/.aws/**)","Read(~/.gnupg/**)","Read(~/.kube/**)","Read(~/.config/gh/**)","Read(~/.netrc)","Read(~/.npmrc)"]}}'

echo "== 기준을 만족하는 설정"
mk; user "$GOOD"
expect "엄격 설정은 문제 없음" 0 "문제 없음" "[HIGH" run
mk; user "$GOOD"; proj '{"hooks":{"PreToolUse":[{"matcher":"Bash"}]}}'
expect "훅이 있으면 INFO만, 종료 코드 0" 0 "outside-sandbox" "[HIGH" run

echo "== 샌드박스 자체"
mk
expect "설정 파일이 없으면 sandbox-off HIGH" 2 "sandbox-off" "" run
mk; user '{"sandbox":{"enabled":false}}'
expect "enabled:false는 HIGH (unattended)" 2 "sandbox-off" "" run
expect "interactive에서는 sandbox-off가 MEDIUM" 1 "[MEDIUM] sandbox-off" "[HIGH" run --profile interactive
mk; user '{"sandbox":{"enabled":true,"allowUnsandboxedCommands":false}}'
expect "failIfUnavailable 없음은 fail-open HIGH" 2 "fail-open" "" run
expect "interactive에서는 fail-open을 보지 않음" 1 "" "fail-open" run --profile interactive
mk; user '{"sandbox":{"enabled":true,"failIfUnavailable":true}}'
expect "allowUnsandboxedCommands 기본값은 HIGH" 2 "unsandboxed-retry" "" run
mk; user '{"sandbox":{"enabled":true,"failIfUnavailable":true,"allowUnsandboxedCommands":false}}'; proj '{"sandbox":{"allowUnsandboxedCommands":true}}'
expect "사용자의 false는 프로젝트의 true보다 우선 (재시도 규칙 없음)" 1 "" "unsandboxed-retry" run
mk; user '{"sandbox":{"enabled":true}}'; loc '{"sandbox":{"enabled":false}}'
expect "local이 user를 덮어 꺼짐" 2 "sandbox-off" "" run

echo "== 프로젝트에서 무시되는 키"
mk; user "$GOOD"; proj '{"sandbox":{"network":{"strictAllowlist":true},"allowNestedUserNamespaces":true}}'
expect "프로젝트의 strictAllowlist는 ignored-in-project" 2 "ignored-in-project" "" run
mk; user '{"sandbox":{"enabled":true,"failIfUnavailable":true,"allowUnsandboxedCommands":false}}'; proj '{"sandbox":{"network":{"strictAllowlist":true}}}'
expect "프로젝트에만 있으면 no-strict-allowlist도 같이" 1 "no-strict-allowlist" "" run
mk; user "$GOOD"; proj '{"sandbox":{"credentials":{"envVars":[{"name":"GITHUB_TOKEN","mode":"mask"}]}}}'
expect "프로젝트의 mask 항목은 무시된다고 알림" 1 "mask" "" run

echo "== 약화 플래그"
mk; user "$GOOD"; proj '{"sandbox":{"enableWeakerNestedSandbox":true}}'
expect "enableWeakerNestedSandbox는 HIGH" 2 "weakening-flag" "" run
mk; user "$GOOD"; user '{"sandbox":{"enabled":true,"failIfUnavailable":true,"allowUnsandboxedCommands":false,"network":{"strictAllowlist":true,"allowAllUnixSockets":true},"filesystem":{"disabled":true}}}'
expect "allowAllUnixSockets·filesystem.disabled도 HIGH" 2 "allowAllUnixSockets" "" run

echo "== 자격 증명·읽기"
mk; user '{"sandbox":{"enabled":true,"failIfUnavailable":true,"allowUnsandboxedCommands":false,"network":{"strictAllowlist":true}}}'
expect "자격 증명 deny가 없으면 cred-not-denied" 1 "~/.ssh" "" run
mk; user '{"sandbox":{"enabled":true,"failIfUnavailable":true,"allowUnsandboxedCommands":false,"network":{"strictAllowlist":true},"filesystem":{"denyRead":["~"]}}}'
expect "denyRead:~ 하나가 모든 자격 증명 경로를 덮음" 1 "read-tool-gap" "cred-not-denied" run
mk; user '{"sandbox":{"enabled":true,"failIfUnavailable":true,"allowUnsandboxedCommands":false,"network":{"strictAllowlist":true},"filesystem":{"denyRead":["~/.ssh"]}}}'
expect "sandbox deny만 있고 Read 규칙이 없으면 read-tool-gap" 1 "read-tool-gap" "" run
mk; user '{"sandbox":{"enabled":true,"failIfUnavailable":true,"allowUnsandboxedCommands":false,"network":{"strictAllowlist":true},"filesystem":{"denyRead":["~/.ssh"]}},"permissions":{"deny":["Read(~/.ssh/**)"]}}'
expect "Read(~/.ssh/**) 규칙이 있으면 read-tool-gap 없음" 1 "" "read-tool-gap" run
mk; user '{"sandbox":{"enabled":true,"failIfUnavailable":true,"allowUnsandboxedCommands":false,"network":{"strictAllowlist":true},"filesystem":{"denyRead":["'"$H"'/.ssh"]}},"permissions":{"deny":["Read(~/.ssh/**)"]}}'
expect "절대 경로(홈 하위)도 ~로 맞춰 비교" 1 "" "read-tool-gap" run

echo "== excludedCommands"
mk; user "$GOOD"; proj '{"sandbox":{"excludedCommands":["bash *"]}}'
expect "bash *는 HIGH broad-exclude" 2 "broad-exclude" "" run
mk; user "$GOOD"; proj '{"sandbox":{"excludedCommands":["*"]}}'
expect "*는 HIGH" 2 "broad-exclude" "" run
mk; user "$GOOD"; proj '{"sandbox":{"excludedCommands":["docker *"]}}'
expect "docker *는 MEDIUM narrow-exclude" 1 "narrow-exclude" "[HIGH" run
mk; user "$GOOD"; proj '{"sandbox":{"excludedCommands":["docker compose up *"]}}'
expect "docker compose up *는 통과" 0 "문제 없음" "narrow-exclude" run

echo "== 허용 도메인"
mk; user "$GOOD"; proj '{"sandbox":{"network":{"allowedDomains":["*"]}}}'
expect "* 는 HIGH broad-domain" 2 "broad-domain" "" run
mk; user "$GOOD"; proj '{"sandbox":{"network":{"allowedDomains":["*.io"]}}}'
expect "*.io 같은 TLD 와일드카드는 HIGH" 2 "broad-domain" "" run
mk; user "$GOOD"; proj '{"sandbox":{"network":{"allowedDomains":["*.example.com"]}}}'
expect "*.example.com은 통과" 0 "문제 없음" "broad-domain" run
mk; user "$GOOD"; proj '{"sandbox":{"network":{"allowedDomains":["me.github.io","bucket.s3.amazonaws.com"]}}}'
expect "공용 호스팅은 MEDIUM shared-host-domain" 1 "shared-host-domain" "[HIGH" run

echo "== 쓰기 범위"
mk; user "$GOOD"; proj '{"sandbox":{"filesystem":{"allowWrite":["~"]}}}'
expect "~ 전체 쓰기는 HIGH broad-write" 2 "broad-write" "" run
mk; user "$GOOD"; proj '{"sandbox":{"filesystem":{"allowWrite":["~/.ssh"]}}}'
expect "~/.ssh 쓰기는 MEDIUM sensitive-write" 1 "sensitive-write" "[HIGH" run
mk; user "$GOOD"; proj '{"sandbox":{"filesystem":{"allowWrite":["~/.config"]}}}'
expect "~/.config 쓰기도 sensitive-write" 1 "sensitive-write" "" run
mk; user "$GOOD"; proj '{"sandbox":{"filesystem":{"allowWrite":["/tmp/build","~/work/out"]}}}'
expect "/tmp/build, ~/work/out은 통과" 0 "문제 없음" "write" run

echo "== bypassPermissions·프록시"
mk; user '{"sandbox":{"enabled":true},"permissions":{"defaultMode":"bypassPermissions"}}'
expect "bypass + 느슨한 샌드박스는 HIGH" 2 "bypass-unsandboxed" "" run
mk; user "$GOOD"; proj '{"permissions":{"defaultMode":"bypassPermissions"}}'
expect "bypass + 엄격 샌드박스는 bypass 규칙 없음" 0 "문제 없음" "bypass-unsandboxed" run
mk; user "$GOOD"; proj '{"sandbox":{"network":{"httpProxyPort":8080}}}'
expect "자체 프록시 포트는 MEDIUM own-proxy" 1 "own-proxy" "" run

echo "== 입력·출력"
mk; user '{"sandbox":'
expect "깨진 JSON은 parse-error HIGH" 2 "parse-error" "" run
mk; user "$GOOD"
expect "settings.json 파일을 직접 점검" 0 "문제 없음" "" $L "$H/.claude/settings.json" --home "$T/none" --no-managed
mk; user "$GOOD"; printf '%s' '{"sandbox":{"enabled":false}}' > "$T/managed.json"
expect "관리형 설정이 사용자 설정을 덮음" 2 "sandbox-off" "" $L "$P" --home "$H" --managed "$T/managed.json"
mk; user '{"sandbox":{"enabled":false}}'
expect "--ignore로 규칙 끄기 (sandbox-off만 사라짐)" 2 "unsandboxed-retry" "sandbox-off" run --ignore sandbox-off
expect "알 수 없는 --ignore id는 3" 3 "알 수 없는 규칙" "" run --ignore nope
expect "없는 경로는 3" 3 "경로가 없다" "" $L "$T/nope" --home "$H"
expect "--json 출력은 파싱된다" 2 '"findings"' "" run --json
out="$(run --json 2>&1)"; if printf '%s' "$out" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["findings"][0]["id"]' 2>/dev/null; then pass=$((pass+1)); echo "  ✅ JSON이 유효하고 findings[0].id가 있음"; else fail=$((fail+1)); echo "  ❌ JSON 파싱 실패"; fi
out="$($L --print-baseline)"; if printf '%s' "$out" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["sandbox"]["failIfUnavailable"] is True' 2>/dev/null; then pass=$((pass+1)); echo "  ✅ --print-baseline은 유효한 JSON"; else fail=$((fail+1)); echo "  ❌ baseline JSON 실패"; fi
# 권장 설정 조각을 사용자 설정으로 쓰면 SELF 점검을 통과한다 (HIGH 없음)
mk; $L --print-baseline > "$H/.claude/settings.json"
expect "baseline 자체가 HIGH 없이 통과" 1 "cred-not-denied" "[HIGH" run

echo
echo "통과 $pass · 실패 $fail"
[ "$fail" -eq 0 ]
