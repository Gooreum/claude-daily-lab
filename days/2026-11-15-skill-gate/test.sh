#!/usr/bin/env bash
# skill-gate 테스트: 키·모델·네트워크 없이 돈다. 이 폴더에서 `bash test.sh`.
cd "$(dirname "$0")" || exit 1
export PYTHONDONTWRITEBYTECODE=1
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
SG="python3 skill_gate.py"
PASS=0; FAIL=0
ok()  { echo "ok   - $1"; PASS=$((PASS+1)); }
bad() { echo "FAIL - $1"; [ -n "${2:-}" ] && echo "       $2"; FAIL=$((FAIL+1)); }
has() { echo "$1" | grep -qF -- "$2"; }
# mk <프로젝트> <스킬> : 표준입력이 SKILL.md
mk() { mkdir -p "$T/$1/.claude/skills/$2"; cat > "$T/$1/.claude/skills/$2/SKILL.md"; }
settings() { mkdir -p "$T/$1/.claude"; cat > "$T/$1/.claude/$2"; }   # settings <프로젝트> <파일명>
verdict_of() { echo "$1" | grep -E "^[A-Z-]+ +$2 " | awk '{print $1}'; }

# --- 프로젝트 A: 선언 방식별 스킬 ---
mk a inline <<'X'
---
name: inline
description: 한 줄 allowed-tools
allowed-tools: Bash(git *) Read
---
본문
X
mk a listy <<'X'
---
name: listy
description: 목록형 allowed-tools
allowed-tools:
  - Bash(ls *)
  - Read
---
본문
X
mk a hooky <<'X'
---
name: hooky
description: hooks 만 선언
hooks:
  PreToolUse:
    - matcher: Bash
      hooks:
        - type: command
          command: "echo hi"
---
본문
X
mk a plain <<'X'
---
name: plain
description: 아무것도 선언 안 함
---
본문
X
mk a emptytools <<'X'
---
name: emptytools
description: 빈 선언
allowed-tools: []
hooks:
---
본문
X
mk a folder-name <<'X'
---
description: name 키 없음 — 폴더 이름을 쓴다
allowed-tools: Read
---
본문
X
OUT=$($SG "$T/a" 2>&1); RC=$?
[ "$RC" = 1 ] && ok "허용 규칙이 빠졌으면 exit 1" || bad "exit 1 기대" "rc=$RC"
[ "$(verdict_of "$OUT" inline)" = NEEDS-ALLOW ] && ok "한 줄 allowed-tools → NEEDS-ALLOW" || bad "inline" "$OUT"
[ "$(verdict_of "$OUT" listy)" = NEEDS-ALLOW ] && ok "목록형 allowed-tools → NEEDS-ALLOW" || bad "listy" "$OUT"
[ "$(verdict_of "$OUT" hooky)" = NEEDS-ALLOW ] && ok "hooks 만 있어도 NEEDS-ALLOW" || bad "hooky" "$OUT"
[ "$(verdict_of "$OUT" plain)" = FREE ] && ok "선언 없는 스킬 → FREE" || bad "plain" "$OUT"
[ "$(verdict_of "$OUT" emptytools)" = FREE ] && ok "allowed-tools: [] / 빈 hooks: → FREE" || bad "emptytools" "$OUT"
[ "$(verdict_of "$OUT" folder-name)" = NEEDS-ALLOW ] && ok "name 키 없으면 폴더 이름 사용" || bad "folder-name" "$OUT"
has "$OUT" "hooks" && has "$OUT" "[allowed-tools]" && ok "선언 종류(allowed-tools·hooks)를 표시" || bad "선언 종류 표시" "$OUT"

# --- 출력: --print-allow ---
SNIP=$($SG "$T/a" --print-allow 2>&1)
echo "$SNIP" | python3 -c 'import json,sys; d=json.load(sys.stdin); a=d["permissions"]["allow"]; assert a==["Skill(folder-name)","Skill(hooky)","Skill(inline)","Skill(listy)"], a' \
  && ok "--print-allow 는 이름순 Skill(이름) JSON 조각" || bad "--print-allow" "$SNIP"
$SG "$T/a" --json | python3 -c 'import json,sys; d=json.load(sys.stdin); assert len(d["skills"])==6 and d["allow_snippet"]["permissions"]["allow"]' \
  && ok "--json 구조(skills·allow_snippet)" || bad "--json"
QOUT=$($SG "$T/a" --quiet); has "$QOUT" "plain" && bad "--quiet 에 FREE 가 나옴" || ok "--quiet 는 FREE 를 숨김"

# --- 허용 규칙을 넣으면 ALLOWED, 모두 갖추면 exit 0 ---
settings a settings.json <<'X'
{"permissions": {"allow": ["Skill(inline)", "Skill(listy *)", "Skill(hooky:*)", "Skill(folder-name)", "Bash(ls *)"]}}
X
OUT=$($SG "$T/a" 2>&1); RC=$?
[ "$RC" = 0 ] && ok "규칙을 모두 갖추면 exit 0" || bad "exit 0 기대" "rc=$RC $OUT"
[ "$(verdict_of "$OUT" listy)" = ALLOWED ] && [ "$(verdict_of "$OUT" hooky)" = ALLOWED ] && ok "'이름 *'·'이름:*' 형태도 허용으로 인정" || bad "와일드카드 형태" "$OUT"
has "$OUT" "빠진 규칙" && bad "빠진 규칙이 없는데 조각을 출력" || ok "빠진 규칙이 없으면 조각을 안 냄"

# --- 일부 규칙 부족: 이름이 비슷해도 다른 스킬은 허용 안 됨 ---
settings a settings.json <<'X'
{"permissions": {"allow": ["Skill(inlin)", "Skill(inline-extra)"]}}
X
OUT=$($SG "$T/a" 2>&1)
[ "$(verdict_of "$OUT" inline)" = NEEDS-ALLOW ] && ok "이름이 부분만 같은 규칙은 허용이 아님" || bad "부분 일치 오인" "$OUT"

# --- settings.local.json 도 읽고, 맨 Skill 은 전체 허용 ---
settings a settings.json <<'X'
{"permissions": {"allow": []}}
X
settings a settings.local.json <<'X'
{"permissions": {"allow": ["Skill"]}}
X
OUT=$($SG "$T/a" 2>&1); RC=$?
[ "$RC" = 0 ] && ok "settings.local.json 의 'Skill' 은 전체 허용" || bad "local 전체 허용" "rc=$RC $OUT"

# --- deny / ask 가 allow 보다 우선 ---
settings a settings.local.json <<'X'
{"permissions": {"allow": ["Skill(inline)", "Skill(listy)", "Skill(hooky)", "Skill(folder-name)"], "deny": ["Skill(inline)"], "ask": ["Skill(listy)"]}}
X
OUT=$($SG "$T/a" 2>&1); RC=$?
[ "$(verdict_of "$OUT" inline)" = DENIED ] && ok "deny 가 allow 보다 우선 → DENIED" || bad "DENIED" "$OUT"
[ "$(verdict_of "$OUT" listy)" = ASK ] && ok "ask 가 allow 보다 우선 → ASK" || bad "ASK" "$OUT"
[ "$RC" = 1 ] && ok "DENIED·ASK 도 exit 1" || bad "DENIED/ASK exit" "rc=$RC"
$SG "$T/a" --print-allow | python3 -c 'import json,sys; assert json.load(sys.stdin)["permissions"]["allow"]==[]' \
  && ok "DENIED·ASK 는 허용 조각에 넣지 않는다(규칙을 지우라는 뜻이 아니므로)" || bad "조각에 DENIED 포함"

# --- 프로젝트별 설정 분리 ---
mk b other <<'X'
---
name: other
description: b 프로젝트 스킬
allowed-tools: Read
---
본문
X
settings b settings.json <<'X'
{"permissions": {"allow": ["Skill(other)"]}}
X
OUT=$($SG "$T/b" 2>&1); RC=$?
[ "$RC" = 0 ] && ok "다른 프로젝트 규칙은 그 프로젝트 설정으로 판정" || bad "프로젝트 b" "rc=$RC $OUT"
OUT=$($SG "$T/a" "$T/b" 2>&1)
[ "$(verdict_of "$OUT" other)" = ALLOWED ] && [ "$(verdict_of "$OUT" inline)" = DENIED ] && ok "경로 둘을 함께 줘도 설정이 섞이지 않음" || bad "설정 섞임" "$OUT"

# --- --settings 로 사용자 설정 추가 ---
mk c solo <<'X'
---
name: solo
description: 사용자 전역 규칙으로 허용
allowed-tools: Read
---
본문
X
echo '{"permissions":{"allow":["Skill(solo)"]}}' > "$T/user.json"
$SG "$T/c" >/dev/null 2>&1; [ $? = 1 ] && ok "전역 규칙 없이는 NEEDS-ALLOW" || bad "전역 전"
$SG "$T/c" --settings "$T/user.json" >/dev/null 2>&1; [ $? = 0 ] && ok "--settings 로 전역 규칙을 더하면 통과" || bad "--settings"

# --- ! 주입 줄 감지(일반 펜스 안의 예시는 제외) ---
mk d inject <<'X'
---
name: inject
description: 주입 줄
---
최근 변경:
!`git log --oneline -3`

```!
date
```

```bash
!`echo 예시일 뿐`
```
X
OUT=$($SG "$T/d" 2>&1)
has "$OUT" "! 주입 줄 2개(줄 6,8)" && ok "! 주입 줄은 인라인과 느낌표 펜스만 세고 일반 펜스 안은 제외" || bad "주입 줄" "$OUT"
[ "$(verdict_of "$OUT" inject)" = FREE ] && ok "주입 줄만으로는 게이트 대상이 아님(참고만)" || bad "inject verdict" "$OUT"

# --- 오류 처리 ---
mk e broken <<'X'
---
name: broken
description: 설정 JSON 이 깨짐
allowed-tools: Read
---
본문
X
echo '{ not json' > "$T/e/.claude/settings.json"
OUT=$($SG "$T/e" 2>&1); RC=$?
has "$OUT" "JSON으로 읽지 못함" && [ "$(verdict_of "$OUT" broken)" = NEEDS-ALLOW ] && [ $RC = 1 ] && ok "깨진 settings.json 은 경고 후 규칙 없음으로 처리" || bad "깨진 JSON" "rc=$RC $OUT"
$SG /no/such/path >/dev/null 2>&1; [ $? = 2 ] && ok "없는 경로는 exit 2" || bad "exit 2(경로)"
mkdir -p "$T/empty"; $SG "$T/empty" >/dev/null 2>&1; [ $? = 2 ] && ok "SKILL.md 없는 폴더는 exit 2" || bad "exit 2(빈 폴더)"
$SG "$T/c" --settings /no/such.json >/dev/null 2>&1; [ $? = 2 ] && ok "없는 --settings 파일은 exit 2" || bad "exit 2(--settings)"

# --- 이 저장소 실제 스킬(읽기 전용) ---
REPO=../../.claude/skills
if [ -d "$REPO/daily-lab" ]; then
  OUT=$($SG "$REPO" 2>&1)
  has "$OUT" "daily-lab " && ok "이 저장소 daily-lab 스킬을 읽음" || bad "실제 스킬" "$OUT"
fi

echo; echo "통과 $PASS · 실패 $FAIL"
[ "$FAIL" = 0 ]
