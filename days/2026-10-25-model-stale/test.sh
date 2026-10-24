#!/usr/bin/env bash
# model-stale 단위 테스트. 키·네트워크·모델 호출 없음.
set -u
cd "$(dirname "$0")"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ✓ $1"; }
bad() { FAIL=$((FAIL+1)); echo "  ✗ $1"; [ -n "${2:-}" ] && echo "      $2"; }
LINT="python3 model_stale.py"
TODAY="--today 2026-10-25"
# (규칙:줄:수준) 목록
trip() { $LINT --json $TODAY "$@" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(" ".join("%s:%s:%s" % (f["rule"], f["line"], f["level"]) for f in d["findings"]))'; }
has() { case " $1 " in *" $2 "*) return 0;; *) return 1;; esac; }
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT

echo "[1] 종료 코드"
$LINT $TODAY fixtures/app >/dev/null 2>&1; [ $? -eq 1 ] && ok "error가 있으면 exit 1" || bad "exit 1 기대"
$LINT $TODAY fixtures/clean >/dev/null 2>&1; [ $? -eq 0 ] && ok "최신 ID·비모델 이름만 있으면 exit 0" || bad "clean exit 0 기대"
$LINT $TODAY fixtures/app --min-level info --ignore M01 --exclude '*.bin' fixtures/clean >/dev/null 2>&1; [ $? -eq 1 ] && ok "--min-level info + M01 끔 → warn/info로 exit 1" || bad "min-level info exit 1 기대"
$LINT $TODAY fixtures/app/bedrock.ts --ignore M01 >/dev/null 2>&1; [ $? -eq 0 ] && ok "M01 끄면 warn만 남아 exit 0" || bad "M01 끈 exit 0 기대"
$LINT $TODAY /no/such/path >/dev/null 2>&1; [ $? -eq 2 ] && ok "없는 경로는 exit 2" || bad "exit 2 기대"
$LINT $TODAY fixtures/app --ignore M99 >/dev/null 2>&1; [ $? -eq 2 ] && ok "모르는 규칙 --ignore는 exit 2" || bad "exit 2 기대(--ignore M99)"
$LINT --today 2026-13-01 fixtures/app >/dev/null 2>&1; [ $? -eq 2 ] && ok "잘못된 --today는 exit 2" || bad "exit 2 기대(--today)"

echo "[2] chat.py — 규칙별 판정"
R=$(trip fixtures/app/chat.py)
for r in M01:6:error M01:7:error M02:10:warn M04:13:info M03:16:warn M03:19:warn M06:19:info M05:22:warn; do
  has "$R" "$r" && ok "$r" || bad "$r 미검출" "got: $R"
done
has "$R" "M04:16:info" && bad "M03이 있는 줄에 M04 중복" "got: $R" || ok "M03이 있으면 M04는 접는다"
for l in 25 28 30; do
  case "$R" in *":$l:"*) bad "허용/최신 줄 $l이 걸림" "got: $R";; *) ok "줄 $l 통과(최신·허용 표시)";; esac
done

echo "[3] 플랫폼 형식 정규화"
R=$(trip fixtures/app/bedrock.ts)
for r in M02:1:warn M03:2:warn M03:3:warn M01:5:error; do
  has "$R" "$r" && ok "bedrock.ts $r" || bad "bedrock.ts $r 미검출" "got: $R"
done
case "$R" in *":4:"*) bad "us.anthropic.claude-opus-5-5가 걸림" "got: $R";; *) ok "리전 접두 최신 ID 통과";; esac
R=$(trip fixtures/app/env.sample)
has "$R" "M01:1:error" && ok "env.sample 설정 파일도 스캔" || bad ".env.example 미검출" "got: $R"
case "$R" in *":2:"*) bad "claude-code가 모델 ID로 걸림" "got: $R";; *) ok "claude-code는 모델 ID가 아님";; esac

echo "[4] 날짜 의존 — 같은 파일, 다른 기준일"
printf 'm = "claude-sonnet-4-5"\n' > "$T/a.py"
R=$($LINT --json --today 2026-10-25 "$T/a.py" | python3 -c 'import json,sys; print(" ".join(f["rule"]+":"+f["level"] for f in json.load(sys.stdin)["findings"]))')
[ "$R" = "M02:warn" ] && ok "11-30 전: M02 warn" || bad "M02 warn 기대" "got: $R"
R=$($LINT --json --today 2026-12-01 "$T/a.py" | python3 -c 'import json,sys; print(" ".join(f["rule"]+":"+f["level"] for f in json.load(sys.stdin)["findings"]))')
[ "$R" = "M02:error" ] && ok "11-30 뒤: M02 error" || bad "M02 error 기대" "got: $R"
printf 'm = "claude-opus-4-5"\n' > "$T/b.py"
R=$($LINT --json --today 2026-06-01 "$T/b.py" | python3 -c 'import json,sys; print(" ".join(f["rule"] for f in json.load(sys.stdin)["findings"]))')
[ "$R" = "M04 M06" ] || [ "$R" = "M04" ] && ok "퇴역일이 90일보다 먼 날엔 M03 없음" || bad "M03 없어야 함" "got: $R"
R=$($LINT --json --today 2026-10-25 --warn-days 10 "$T/b.py" | python3 -c 'import json,sys; print(" ".join(f["rule"] for f in json.load(sys.stdin)["findings"]))')
case "$R" in *M03*) bad "--warn-days 10인데 D-30이 걸림" "got: $R";; *) ok "--warn-days 10이면 D-30은 M03 아님";; esac

echo "[5] 파일 처리"
R=$($LINT --json $TODAY fixtures/app | python3 -c 'import json,sys; print(sorted({f["file"].split("/")[-1] for f in json.load(sys.stdin)["findings"]}))')
case "$R" in *blob.bin*) bad "바이너리 파일을 읽음" "got: $R";; *) ok "NUL 바이트 파일은 건너뜀";; esac
mkdir -p "$T/p/node_modules/x" "$T/p/src"; echo 'x="claude-3-opus-20240229"' > "$T/p/node_modules/x/i.js"; echo 'x="claude-3-opus-20240229"' > "$T/p/src/i.js"; echo 'x="claude-3-opus-20240229"' > "$T/p/CHANGELOG.md"
R=$($LINT --json $TODAY --exclude 'CHANGELOG*' "$T/p" | python3 -c 'import json,sys; print(sorted(f["file"].replace("'"$T"'/","") for f in json.load(sys.stdin)["findings"]))')
[ "$R" = "['p/src/i.js']" ] && ok "node_modules 건너뜀 · --exclude glob" || bad "src/i.js만 기대" "got: $R"
mkdir -p "$T/q/fixtures" "$T/q/lib"; echo 'x="claude-3-opus-20240229"' > "$T/q/fixtures/f.py"; echo 'x="claude-3-opus-20240229"' > "$T/q/lib/l.py"
R=$($LINT --json $TODAY --exclude fixtures "$T/q" | python3 -c 'import json,sys; print(sorted(f["file"].replace("'"$T"'/","") for f in json.load(sys.stdin)["findings"]))')
[ "$R" = "['q/lib/l.py']" ] && ok "--exclude는 폴더 이름도 건너뜀" || bad "q/lib/l.py만 기대" "got: $R"
$LINT $TODAY --summary fixtures/app | grep -q '^| `claude-opus-4-1-20250805` | error | 1 | 1 |' && ok "--summary 표" || bad "--summary 표 미출력"

echo "[6] 표 낡음 경고"
$LINT --today 2026-12-31 fixtures/clean | grep -q '모델 표가 .*일 전' && ok "45일 넘으면 갱신 경고" || bad "낡은 표 경고 기대"
$LINT $TODAY fixtures/clean | grep -q '모델 표가' && bad "하루 된 표에 경고" || ok "신선한 표엔 경고 없음"

echo "[7] --import (공식 페이지 → 표)"
cp models.json "$T/m.json"
python3 model_stale.py --import fixtures/deprecations-2026-10-24.md --table "$T/m.json" --today 2026-10-24 | grep -q '추가 0 \[\] · 변경 0' && ok "같은 페이지를 다시 가져오면 변화 없음" || bad "재import 변화 없어야 함"
sed 's/| claude-sonnet-4-5-20250929 | Deprecated    | September 30, 2026 | November 30, 2026                  |/| claude-sonnet-4-5-20250929 | Retired       | September 30, 2026 | November 30, 2026                  |/; s/^| claude-haiku-5-5 .*$/&\n| claude-opus-6-1            | Active        | N\/A                | Not sooner than January 1, 2028    |/' fixtures/deprecations-2026-10-24.md > "$T/new.md"
OUT=$(python3 model_stale.py --import "$T/new.md" --table "$T/m.json" --today 2026-12-01)
echo "$OUT" | grep -q "추가 1 \['claude-opus-6-1'\] · 변경 1 \['claude-sonnet-4-5-20250929'\]" && ok "새 모델 1 추가 · 상태 변경 1 감지" || bad "import 요약 불일치" "got: $OUT"
printf 'm = "claude-sonnet-4-5"\nn = "claude-opus-6-1"\n' > "$T/c.py"
R=$($LINT --json --today 2026-12-01 --table "$T/m.json" "$T/c.py" | python3 -c 'import json,sys; print(" ".join(f["rule"]+":"+f["level"] for f in json.load(sys.stdin)["findings"]))')
[ "$R" = "M01:error" ] && ok "갱신 표 반영: Retired → M01, 새 최고 버전은 통과" || bad "갱신 표 판정 불일치" "got: $R"
echo "no table here" > "$T/bad.md"
python3 model_stale.py --import "$T/bad.md" --table "$T/m2.json" >/dev/null 2>&1; [ $? -eq 2 ] && ok "표를 못 찾는 페이지는 exit 2" || bad "exit 2 기대(bad page)"

echo
echo "통과 $PASS · 실패 $FAIL"
[ "$FAIL" -eq 0 ]
