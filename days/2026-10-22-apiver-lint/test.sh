#!/usr/bin/env bash
# apiver-lint 단위 테스트. 키·네트워크·모델 호출 없음.
set -u
cd "$(dirname "$0")"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ✓ $1"; }
bad() { FAIL=$((FAIL+1)); echo "  ✗ $1"; [ -n "${2:-}" ] && echo "      $2"; }
LINT="python3 apiver_lint.py"
# 파일(또는 폴더)의 (규칙:줄:레벨) 목록
trip() { $LINT --json "$@" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(" ".join("%s:%s:%s" % (f["rule"], f["line"], f["level"]) for f in d["findings"]))'; }
has() { case " $1 " in *" $2 "*) return 0;; *) return 1;; esac; }
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT

echo "[1] 종료 코드"
$LINT fixtures >/dev/null 2>&1; [ $? -eq 1 ] && ok "error가 있으면 exit 1" || bad "exit 1 기대"
$LINT fixtures/clean >/dev/null 2>&1; [ $? -eq 0 ] && ok "깨끗한 폴더는 exit 0" || bad "clean exit 0 기대"
$LINT fixtures/admin >/dev/null 2>&1; [ $? -eq 0 ] && ok "warn만 있으면 exit 0" || bad "warn만 있는데 exit 0 아님"
$LINT /no/such/path >/dev/null 2>&1; [ $? -eq 2 ] && ok "없는 경로는 exit 2" || bad "exit 2 기대"
$LINT fixtures --ignore V99 >/dev/null 2>&1; [ $? -eq 2 ] && ok "모르는 규칙 --ignore는 exit 2" || bad "exit 2 기대(--ignore V99)"

echo "[2] py_app — 파이썬 규칙"
R=$(trip fixtures/py_app/app.py)
for r in V08:4:error V09:8:error V01:12:error V01:13:error V02:17:warn V03:20:warn V11:27:error V05:30:info; do
  has "$R" "$r" && ok "$r" || bad "$r 미검출" "got: $R"
done
R=$(trip fixtures/py_app/requirements.txt)
has "$R" "V04:1:info" && ok "anthropic<2 핀 → info" || bad "requirements 핀 미검출" "got: $R"

echo "[3] ts_app — TypeScript 규칙"
R=$(trip fixtures/ts_app/run.ts)
for r in V10:7:error V06:11:error V01:12:error; do has "$R" "$r" && ok "$r" || bad "$r 미검출" "got: $R"; done
R=$(trip fixtures/ts_app/package.json)
has "$R" "V04:5:error" && ok "sdk 1.x + bedrock-sdk 0.x 어긋남 → error" || bad "플랫폼 패키지 짝 미검출" "got: $R"

echo "[4] 게이트웨이·Go·Admin"
R=$(trip fixtures/gateway/nginx.conf)
for r in V07:4:warn V07:5:warn; do has "$R" "nginx $r" || has "$R" "$r" && ok "nginx.conf $r" || bad "nginx.conf $r 미검출" "got: $R"; done
R=$(trip fixtures/gateway/proxy.js)
has "$R" "V07:4:warn" && ok "proxy.js req.headers[\"x-api-key\"] V07:4" || bad "proxy.js V07 미검출" "got: $R"
R=$(trip fixtures/go_app)
for r in V04:5:info V12:2:info V06:3:error; do has "$R" "$r" && ok "$r" || bad "$r 미검출" "got: $R"; done
R=$(trip fixtures/admin/report.py)
for r in V13:6:warn V13:11:warn V13:13:warn V13:15:warn; do has "$R" "$r" && ok "$r" || bad "$r 미검출" "got: $R"; done
has "$R" "V13:7:warn" && bad "V13 오탐: api_keys 루프의 k[\"name\"]이 RBAC name으로 잡힘" || ok "V13: 엔드포인트가 먼 name은 안 잡음"

echo "[5] 오탐 방지"
R=$(trip fixtures/clean)
[ -z "$R" ] && ok "clean 폴더: 검출 0" || bad "clean 오탐" "got: $R"
cat > "$T/hi.py" <<'P'
import anthropic
temperature_label = "warm"
obj.temperature = 3
def f(): pass
x = {"citations": {"enabled": True}}
msgs = [{"role": "user", "content": [{"type": "document", "source": {}}]}]
msgs2 = [{"role": "assistant", "content": [{"type": "text", "text": "a", "citations": [{"type": "x"}]}]}]
page = client.beta.models.list(betas=["x"])
# temperature=0.1 주석
print("백틱으로 감싼 설명 `temperature: 1`은 코드가 아니다", anthropic)
P
R=$(trip "$T/hi.py")
[ -z "$R" ] && ok "변수명·속성·주석·백틱 설명·user 문서·assistant citations·beta.models는 통과" || bad "오탐" "got: $R"
cat > "$T/web.py" <<'P'
def call(prompt, temperature: float = 0.2):
    return anthropic.Anthropic().messages.create(model="m", messages=[])
P
R=$(trip "$T/web.py")
has "$R" "V01:1:warn" && ok "래퍼 인자 temperature는 warn" || bad "래퍼 인자 레벨 틀림" "got: $R"
printf 'model: claude-sonnet-5-5\ntemperature: 0.3\n' > "$T/cfg.yaml"
R=$(trip "$T/cfg.yaml")
has "$R" "V01:2:warn" && ok "설정 파일 temperature는 warn" || bad "설정 파일 레벨 틀림" "got: $R"

cat > "$T/admin2.py" <<'P'
import anthropic
keys = client.beta.organizations.api_keys.list()
for key in keys:
    where = names.get(key.scope.workspace_id, "Default")
P
R=$(trip "$T/admin2.py"); [ -z "$R" ] && ok "이미 scope.workspace_id를 읽는 코드는 통과" || bad "V13 오탐: scope.workspace_id" "got: $R"
printf '{"text": "POST https://api.anthropic.com/v1/complete max_tokens_to_sample claude"}\n' > "$T/docs.json"
R=$(trip "$T/docs.json"); [ -z "$R" ] && ok "JSON 데이터 속 Text Completions 설명은 통과" || bad "V06 오탐: JSON 데이터" "got: $R"

echo "[6] SDK 핀 판정 (V04)"
check_pin() { # 내용 기대레벨(없으면 none)
  printf '%s\n' "$1" > "$T/requirements.txt"
  local R; R=$(trip "$T/requirements.txt")
  if [ "$2" = none ]; then [ -z "$R" ] && ok "핀 '$1' → 검출 없음" || bad "핀 '$1' 오탐" "got: $R"
  else has "$R" "V04:1:$2" && ok "핀 '$1' → $2" || bad "핀 '$1' 기대 $2" "got: $R"; fi
}
check_pin "anthropic>=1.16,<2" info
check_pin "anthropic==1.17.0" info
check_pin "anthropic~=1.16" info
check_pin "anthropic[bedrock]<=1.99" info
check_pin "anthropic>=2.0.0" none
check_pin "anthropic>=2.0,<3" none
check_pin "anthropic==2.1.0" none
check_pin "anthropic" warn
check_pin "anthropic-foo==1.0" none
printf '[tool.poetry.dependencies]\nanthropic = "^1.16"\n' > "$T/pyproject.toml"
R=$(trip "$T/pyproject.toml"); has "$R" "V04:2:info" && ok "poetry ^1.16 → info" || bad "poetry 핀 미검출" "got: $R"
printf '{"dependencies":{"@anthropic-ai/sdk":"^0.137.0"}}' > "$T/package.json"
R=$(trip "$T/package.json"); has "$R" "V04:1:info" && ok "package.json sdk ^0.137 → info" || bad "sdk 0.x 미검출" "got: $R"
printf '{"dependencies":{"@anthropic-ai/sdk":"^0.137.0","@anthropic-ai/vertex-sdk":"^1.0.0"}}' > "$T/package.json"
R=$(trip "$T/package.json"); has "$R" "V04:1:error" && ok "sdk 0.x + vertex 1.x 어긋남 → error" || bad "역방향 어긋남 미검출" "got: $R"
printf '{"dependencies":{"@anthropic-ai/sdk":"^1.1.0","@anthropic-ai/vertex-sdk":"^1.0.0"}}' > "$T/package.json"
R=$(trip "$T/package.json"); [ -z "$R" ] && ok "둘 다 1.x면 통과" || bad "정상 조합 오탐" "got: $R"

echo "[7] 출력 옵션"
OUT=$($LINT fixtures 2>&1)
has "$OUT" "합계:" && ok "합계 줄" || echo "$OUT" | grep -q "합계: error" && ok "합계 줄" || bad "합계 줄 없음"
echo "$OUT" | grep -q "규칙별: V01×3" && ok "규칙별 집계" || bad "규칙별 집계 틀림"
J=$($LINT --json fixtures --min-level error)
echo "$J" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["findings"] and all(f["level"]=="error" for f in d["findings"]); assert d["summary"]["warn"]==0' && ok "--min-level error는 error만" || bad "--min-level 틀림"
J=$($LINT --json fixtures --ignore V01,V05)
echo "$J" | python3 -c 'import json,sys; d=json.load(sys.stdin); r={f["rule"] for f in d["findings"]}; assert not (r & {"V01","V05"}), r' && ok "--ignore가 규칙을 뺌" || bad "--ignore 틀림"
J=$($LINT --json fixtures --exclude py_app --exclude admin)
echo "$J" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert not any("py_app" in f["file"] or "admin" in f["file"] for f in d["findings"])' && ok "--exclude가 폴더를 건너뜀" || bad "--exclude 틀림"
$LINT --json fixtures | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["summary"]["files_scanned"]>=12' && ok "files_scanned 집계" || bad "files_scanned 틀림"

echo
echo "통과 $PASS · 실패 $FAIL"
[ "$FAIL" -eq 0 ]
