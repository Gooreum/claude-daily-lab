#!/usr/bin/env bash
# test.sh — run_receipt.py 단위 테스트. 키·모델 없이 돈다. 이 폴더에서 `bash test.sh`.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
HERE="$(pwd)"
R="python3 -I $HERE/run_receipt.py"
pass=0; fail=0
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
NOW="2026-10-27T06:50:00+09:00"
fresh="202610270300.00"   # 오늘 03:00 (로컬 시간대 기준 touch) — 아래에서 TZ 고정
export TZ=Asia/Seoul

expect() { # $1=label $2=expected_exit $3=stderr/stdout must contain (optional) ; 나머지=명령
  local label="$1" want="$2" needle="$3"; shift 3
  local out rc; out="$("$@" 2>&1)"; rc=$?
  if [ "$rc" -eq "$want" ] && { [ -z "$needle" ] || [[ "$out" == *"$needle"* ]]; }; then
    pass=$((pass+1)); echo "  ✅ $label (exit=$rc)"
  else
    fail=$((fail+1)); echo "  ❌ $label (exit=$rc, expected $want, needle='$needle')"; echo "$out" | sed 's/^/      /'
  fi
}
mk() { rm -rf "$T/w"; mkdir -p "$T/w/out"; }
spec() { printf '%s' "$1" > "$T/w/spec.json"; }
good_csv() { printf 'id,name\n1,a\n2,b\n' > "$T/w/out/r.csv"; touch -t "$fresh" "$T/w/out/r.csv"; }
good_report() { printf '# 변경\n- a.py 수정\n# 검증\n- pytest 통과 exit 0\n# 가정\n- 없음.\n# 남은 요청\n- 리뷰 필요\n' > "$T/w/REPORT.md"; touch -t "$fresh" "$T/w/REPORT.md"; }
CSV='{"outputs":[{"path":"out/r.csv","min_data_rows":1,"max_age_hours":24}]}'
chk() { $R check "$T/w/spec.json" --now "$NOW" "$@"; }

echo "== 결과 파일"
mk; good_csv; spec "$CSV"
expect "정상 CSV" 0 "영수증: OK" chk
mk; spec "$CSV"
expect "파일 없음" 1 "파일 없음" chk
mk; printf 'id,name\n' > "$T/w/out/r.csv"; touch -t "$fresh" "$T/w/out/r.csv"; spec "$CSV"
expect "헤더만 있는 CSV(종료 코드 0이었어도)" 1 "데이터 줄이 0개" chk
mk; good_csv; touch -t 202610250300.00 "$T/w/out/r.csv"; spec "$CSV"
expect "이틀 전 파일" 1 "오래된 파일" chk
mk; : > "$T/w/out/r.csv"; touch -t "$fresh" "$T/w/out/r.csv"; spec '{"outputs":[{"path":"out/r.csv"}]}'
expect "0바이트 파일" 1 "너무 작음" chk
mk; good_csv; spec '{"outputs":[{"path":"out/r.csv","run_started":"2026-10-27T04:00:00+09:00"}]}'
expect "실행 시작 전에 수정된 파일" 1 "이번 실행이 쓴 파일이 아님" chk
mk; good_csv; spec '{"outputs":[{"path":"out/r.csv","run_started":"2026-10-27T02:00:00+09:00"}]}'
expect "실행 시작 뒤에 수정된 파일" 0 "" chk
mk; good_csv; spec '{"outputs":[{"path":"out/r.csv","must_contain":["name","zzz"]}]}'
expect "필수 문구 누락" 1 "'zzz'" chk
mk; printf '{}' > "$T/w/out/r.json"; touch -t "$fresh" "$T/w/out/r.json"; spec '{"outputs":[{"path":"out/r.json","json":true}]}'
expect "빈 JSON 객체" 1 "비어 있음" chk
mk; printf '{bad' > "$T/w/out/r.json"; touch -t "$fresh" "$T/w/out/r.json"; spec '{"outputs":[{"path":"out/r.json","json":true}]}'
expect "깨진 JSON" 1 "JSON 파싱 실패" chk
mk; printf '{"n":3}' > "$T/w/out/r.json"; touch -t "$fresh" "$T/w/out/r.json"; spec '{"outputs":[{"path":"out/r.json","json":true}]}'
expect "정상 JSON" 0 "" chk
mk; printf 'x\n\n\n' > "$T/w/out/2026-10-27.log"; touch -t "$fresh" "$T/w/out/2026-10-27.log"; spec '{"outputs":[{"path":"out/{date}.log","min_lines":2}]}'
expect "{date} 치환 + 내용 줄 부족" 1 "내용 줄이 1개" chk
mk; printf 'a\nb\n' > "$T/w/out/2026-10-27.log"; touch -t "$fresh" "$T/w/out/2026-10-27.log"; spec '{"outputs":[{"path":"out/{date}.log","min_lines":2}]}'
expect "{date} 치환 정상" 0 "" chk

echo "== 프롬프트 파일"
mk; printf -- '---\nname: nightly\n---\nDo it\n' > "$T/w/p.md"; spec '{"prompt_files":["p.md"]}'
expect "--- 프런트매터로 시작" 1 "옵션으로 읽을 수 있음" chk
mk; printf 'Do the nightly job\n---\n' > "$T/w/p.md"; spec '{"prompt_files":["p.md"]}'
expect "일반 프롬프트" 0 "" chk
mk; printf '\n\n  -v verbose\n' > "$T/w/p.md"; spec '{"prompt_files":["p.md"]}'
expect "앞 공백 뒤 '-'" 1 "'-'" chk
mk; printf '\xef\xbb\xbfhello\n' > "$T/w/p.md"; spec '{"prompt_files":["p.md"]}'
expect "BOM" 1 "BOM" chk
mk; : > "$T/w/p.md"; spec '{"prompt_files":["p.md"]}'
expect "빈 프롬프트" 1 "비어 있음" chk
mk; spec '{"prompt_files":["nope.md"]}'
expect "없는 프롬프트" 1 "읽을 수 없음" chk
mk; printf -- '--x\n' > "$T/w/a.md"; printf 'ok\n' > "$T/w/b.md"
expect "prompt 서브명령: 하나라도 나쁘면 1" 1 "❌" $R prompt "$T/w/a.md" "$T/w/b.md"
expect "prompt 서브명령: 모두 좋으면 0" 0 "✅" $R prompt "$T/w/b.md"

echo "== REPORT.md"
RPT='{"report":{"path":"REPORT.md","sections":["변경","검증","가정","남은"]}}'
mk; good_report; spec "$RPT"
expect "정상 보고서" 0 "" chk
mk; printf '# 변경\n- x\n# 검증\n- y\n# 가정\n없음\n# 남은 요청\n없음\n' > "$T/w/REPORT.md"; touch -t "$fresh" "$T/w/REPORT.md"; spec "$RPT"
expect "'없음'이라고 적은 절은 정상 답" 0 "" chk
mk; spec "$RPT"
expect "보고서 없음" 1 "보고서 없음" chk
mk; printf '# 변경\n- x\n# 검증\n\n# 가정\n- a\n# 남은 요청\n- b\n' > "$T/w/REPORT.md"; touch -t "$fresh" "$T/w/REPORT.md"; spec "$RPT"
expect "빈 절(검증)" 1 "'검증' 절이 비어" chk
mk; printf '# 변경\n- x\n# 검증\n- y\n' > "$T/w/REPORT.md"; touch -t "$fresh" "$T/w/REPORT.md"; spec "$RPT"
expect "절 누락(가정·남은)" 1 "'가정' 절이 없음" chk
mk; printf '# 변경\n- x\n# 검증\nTODO\n# 가정\n- a\n# 남은 요청\n- b\n' > "$T/w/REPORT.md"; touch -t "$fresh" "$T/w/REPORT.md"; spec "$RPT"
expect "TODO만 있는 절" 1 "'검증' 절이 비어" chk
mk; good_report; touch -t 202610250300.00 "$T/w/REPORT.md"; spec "$RPT"
expect "어제 이전 보고서" 1 "오래된 보고서" chk

echo "== BLOCKED.md"
mk; printf 'API 토큰 만료 — 로그인 필요\n시도한 것: 재시도 1회\n' > "$T/w/BLOCKED.md"; spec '{"blocked":"BLOCKED.md","outputs":[{"path":"out/r.csv"}]}'
expect "BLOCKED면 exit 3, 결과 파일 없음은 실패로 세지 않음" 3 "API 토큰 만료" chk
mk; : > "$T/w/BLOCKED.md"; good_csv; spec '{"blocked":"BLOCKED.md","outputs":[{"path":"out/r.csv"}]}'
expect "빈 BLOCKED.md는 무시" 0 "" chk
mk; good_csv; spec '{"blocked":"BLOCKED.md","outputs":[{"path":"out/r.csv"}]}'
expect "BLOCKED.md 없음" 0 "" chk

echo "== 출력 형식과 영수증 파일"
mk; good_csv; spec "$CSV"
expect "--json 출력" 0 '"overall": "OK"' chk --json
chk --write-receipt "$T/w/receipt.json" >/dev/null
if python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["overall"]=="OK" and d["results"][0]["kind"]=="output"' "$T/w/receipt.json"; then
  pass=$((pass+1)); echo "  ✅ --write-receipt JSON"; else fail=$((fail+1)); echo "  ❌ --write-receipt JSON"; fi
expect "여러 검사 중 하나만 실패해도 1" 1 "실패 1" bash -c "cd '$T/w' && printf 'bad{' > out/b.json && touch -t $fresh out/b.json && printf '%s' '{\"outputs\":[{\"path\":\"out/r.csv\"},{\"path\":\"out/b.json\",\"json\":true}]}' > spec.json && python3 -I $HERE/run_receipt.py check spec.json --now $NOW"

echo "== 사용 오류 (exit 2)"
expect "없는 스펙 파일" 2 "스펙을 읽을 수 없음" $R check "$T/none.json"
printf '{oops' > "$T/bad.json"
expect "깨진 스펙 JSON" 2 "스펙을 읽을 수 없음" $R check "$T/bad.json"
expect "서브명령 없음" 2 "" $R

echo "== 결과: pass=$pass fail=$fail"
[ "$fail" -eq 0 ]
