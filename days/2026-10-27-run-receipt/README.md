# run-receipt

## 1. 무엇을 만들었나
무인(야간) `claude -p` 실행이 끝난 **뒤에** "결과가 진짜 있는가"를 확인하는 CLI(`run_receipt.py`, 표준 라이브러리만 사용)다. 스펙 JSON에 적은 대로 결과 파일의 존재·신선도(몇 시간 안에 수정됐나)·크기·헤더만 있는 CSV·빈 JSON·필수 문구, 프롬프트 파일이 `-`/`---`로 시작해 CLI 옵션으로 오해되는지, `REPORT.md`의 필수 절이 비어 있지 않은지, `BLOCKED.md`가 있는지를 본다. 종료 코드는 0=통과, 1=실패, 3=BLOCKED(사람이 볼 차례), 2=사용 오류다.

## 2. 왜 만들었나
2026-10-26 dev.to 글 [What breaks when Claude Code runs overnight with nobody watching](https://dev.to/everydaylentils/what-breaks-when-claude-code-runs-overnight-with-nobody-watching-3ka8)과 [CLAUDE.md Best Practices: A Template for Unattended Agents](https://dev.to/aobaworks/claudemd-best-practices-a-template-for-unattended-agents-1d3j)(news/2026-10-27.md 2·3번)가 계기다. 야간 작업이 "정시에 돌았는데 아무것도 안 한" 사례(프런트매터의 `---`가 옵션으로 읽혀 이틀 밤 연속 종료 코드 1, 데이터가 없는 밤에 헤더만 쓴 CSV가 종료 코드 0)가 직접 만들 만했다. 이 저장소의 `loop-caps`·`spend-gate`는 무인 실행을 *멈추는* 쪽이고, 끝난 뒤 결과가 진짜인지 *확인하는* 도구는 없었다.

## 3. 어떻게 만들었나
1. 검사를 네 종류로 나눴다: `prompt`(프롬프트 파일), `output`(결과 파일), `report`(`REPORT.md`), `blocked`(`BLOCKED.md`). 각각 통과(OK)/실패(FAIL)/BLOCKED 상태와 메시지 목록을 돌려주고, 전체는 이를 합친다.
2. 신선도는 파일 수정 시각을 `--now`(테스트용 고정 시각)와 비교한다. 선택 항목 `run_started`를 주면 "이번 실행이 시작된 뒤에 쓰인 파일인가"까지 본다. 어제 파일이 그대로 남아 "있다"로 통과하는 것을 막기 위해서다.
3. CSV는 `csv` 모듈로 빈 줄을 뺀 줄 수에서 헤더 1줄을 빼 데이터 줄 수를 센다. JSON은 파싱이 되어도 `{}`·`[]`·`null`이면 실패로 본다.
4. `BLOCKED.md`가 비어 있지 않으면 그 첫 줄을 보여 주고 exit 3으로 끝낸다. 막힌 밤은 결과 파일이 없는 게 정상이라 결과 파일 검사는 건너뛴다(실패로 세면 "막혔다"는 신호가 "고장"에 묻힌다).
5. 보고서의 절은 제목에 필수 단어가 **포함**되면 찾은 것으로 본다(`변경` → `## 변경된 파일`). 본문이 공백·목록 기호·`TODO`/`TBD`뿐이면 빈 절이다. `없음`이라고 적은 절은 정상 답으로 본다 — 처음엔 `없음`도 빈 절로 처리해 "가정: 없음"이 실패하는 것을 테스트가 잡아 고쳤다.
6. 프롬프트 점검은 실제 CLI로 확인했다(5절). 파일 첫 글자가 `-`이면 `claude -p "$(cat file)"`이 옵션 오류가 난다.

## 4. 사용법
```bash
cp run_receipt.py spec.example.json /my/nightly/   # 스펙을 내 경로에 맞게 고친다
python3 run_receipt.py check spec.json              # 야간 작업이 끝난 뒤에 실행
python3 run_receipt.py check spec.json --json --write-receipt receipt.json
python3 run_receipt.py prompt nightly-prompt.md     # 프롬프트 파일만 점검
```
스펙(`spec.example.json`): `prompt_files`, `blocked`, `outputs`(각 `path`·`max_age_hours`·`min_bytes`·`min_lines`·`min_data_rows`·`must_contain`·`json`·`run_started`), `report`(`path`·`sections`). 경로에 `{date}`(오늘)·`{yesterday}`를 쓸 수 있고 상대 경로는 스펙 파일 위치 기준이다. 예 — 헤더만 있는 CSV·빈 JSON·`---` 프롬프트·비어 있는 보고서를 일부러 만든 폴더:
```
❌ [prompt] nightly-prompt.md — 첫 글자가 '-'('---') — CLI가 옵션으로 읽을 수 있음. 프롬프트 앞에 `--`를 붙이거나 첫 줄을 바꾸세요
❌ [output] out/2026-10-27-report.csv — 헤더 아래 데이터 줄이 0개 (최소 1) — 헤더만 있는 파일일 수 있음
❌ [output] out/summary.json — JSON은 맞지만 비어 있음 ({})
❌ [report] REPORT.md — 보고서의 '검증' 절이 비어 있음; 보고서에 '가정' 절이 없음; 보고서에 '남은' 절이 없음
영수증: FAIL (4건 중 실패 4)
```
launchd/cron/Actions에서는 `claude -p … ; python3 run_receipt.py check spec.json || notify` 식으로 뒤에 붙인다. 종료 코드 3(BLOCKED)과 1(실패)을 알림에서 구분할 수 있다.

## 5. 테스트 결과
`bash test.sh` (키·모델 없이, 시각을 `--now`로 고정하고 `touch -t`로 수정 시각을 만든다):
```
== 결과 파일   ✅ 13개 (정상 CSV·파일 없음·헤더만 있는 CSV·이틀 전 파일·0바이트·실행 시작 전/후 수정·필수 문구·빈/깨진/정상 JSON·{date} 2개)
== 프롬프트 파일 ✅ 8개 (--- 프런트매터·일반·앞 공백 뒤 '-'·BOM·빈 파일·없는 파일·prompt 서브명령 2개)
== REPORT.md   ✅ 7개 (정상·'없음' 절 정상·보고서 없음·빈 절·절 누락·TODO만·오래된 보고서)
== BLOCKED.md  ✅ 3개 (exit 3·빈 파일 무시·없음)
== 출력 형식    ✅ 3개 (--json·--write-receipt·하나만 실패해도 1)
== 사용 오류    ✅ 3개 (없는 스펙·깨진 스펙·서브명령 없음 → exit 2)
== 결과: pass=37 fail=0
```
`bash e2e.sh` — 실제 `claude` 2.1.311로 실행. 로그인이 없는 러너라 1번(옵션 해석)만 확인되고 2번(모델이 파일을 쓰고 영수증 통과)은 건너뛰었다. 출력 그대로:
```
claude: 2.1.311 (Claude Code)
== 1) 프롬프트가 '---'로 시작
   | error: unknown option '--- ⏎ name: nightly ⏎ ---
  ✅ 그대로 넘기면 CLI가 'unknown option'으로 거부
  ✅ run-receipt prompt가 같은 파일을 실패로 판정
   | Warning: no stdin data received in 3s, proceeding without it. ... ⏎ Not logged in · Please run /login
  ✅ '--'를 붙이면 옵션 해석을 통과
== 2) 모델이 결과 파일을 쓰고 영수증 통과 (로그인 필요)
  ⏭ 로그인 없음 — 2번 건너뜀
== 결과: pass=3 fail=0
```
CI에서는 e2e 미실행(`claude` 로그인 없음). 즉 **글의 `---` 문제는 실제 CLI로 재현됐다.** 반면 `claude -p`가 모델 호출 뒤 실제 결과 파일을 쓰는 경로와 영수증의 결합은 이번에 확인하지 못했다.

## 6. 한계와 다음 아이디어
- e2e 2번(실제 모델이 파일을 쓰는 경로) 미확인. 로그인된 환경에서 `bash e2e.sh`로 먼저 확인해야 한다.
- 파일 내용의 *의미*는 모르고 형태만 본다. 줄이 있어도 틀린 숫자일 수 있다. `must_contain`·`min_data_rows`는 최소 방어선이다.
- 파일 수정 시각을 믿는다. 복사·`touch`로 속일 수 있고, 시각이 다른 서버 사이에서는 어긋난다.
- 다음 아이디어: `claude -p --output-format json` 결과의 `is_error`·`subtype`·`num_turns`를 읽는 검사, 이 저장소 `daily-lab` 실행 뒤 오늘 폴더·`SUMMARY.md`·`news/<오늘>.md` 영수증 스펙(별도 후속), 한도 사용량(`/usage`) 임계 검사.

## 7. 출처
- https://dev.to/everydaylentils/what-breaks-when-claude-code-runs-overnight-with-nobody-watching-3ka8
- https://dev.to/aobaworks/claudemd-best-practices-a-template-for-unattended-agents-1d3j
- https://claude.com/blog/building-agents-when-to-fold-subagents-into-your-main-agent-loop
- https://github.com/anthropics/claude-code/releases/tag/v2.1.311
