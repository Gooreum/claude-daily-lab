# haiku-migrate-lint — Haiku 4.5 → 5.5 마이그레이션 린터

## 1. 무엇을 만들었나
Claude Haiku 4.5용 코드를 Haiku 5.5로 옮길 때 400 에러를 내는 패턴을 정적으로 찾아 주는 CLI 스크립트(`haiku_lint.py`, Python 표준 라이브러리만). 모델 ID·thinking 설정·샘플링 파라미터·assistant prefill·computer 도구 버전·Bedrock 구조화 출력 등 10개 규칙(H01~H10)을 파일·줄 단위로 보고하고, 모델 ID와 도구 버전처럼 기계적인 치환은 `--fix`(또는 `--fix --dry-run` diff)로 적용한다. API 키·네트워크 없이 돈다.

## 2. 왜 만들었나
계기: [API 릴리스 노트 10-07 "Code written for Claude Haiku 4.5 can break on Claude Haiku 5.5"](https://platform.claude.com/docs/en/release-notes/api)와 [Haiku 5.5 마이그레이션 가이드](https://platform.claude.com/docs/en/models/haiku-5-5/migration-guide). 10월 수집([news/2026-10-october-all.md](../../news/2026-10-october-all.md) 15번)의 현실 적용 1번 "여섯 항목을 grep으로 찾아 고친 뒤 교체 → 배포 후 400 폭주 방지"를 그대로 도구로 만들었다. 공식 `/claude-api migrate` 스킬은 모델이 대화형으로 고쳐 주지만, CI에서 키 없이 돌릴 결정론적 검사기가 없어서 그 빈자리를 채운다. Haiku 5.5는 Claude Code 2.1.293부터 기본 Haiku라 이 저장소의 e2e들도 전부 영향을 받는다.

## 3. 어떻게 만들었나
1. 마이그레이션 가이드의 체크리스트 11항목을 읽고 정적으로 잡히는 것만 규칙으로 옮겼다.

| 규칙 | 레벨 | 잡는 것 | 자동 fix |
|---|---|---|---|
| H01 | error | `claude-haiku-4-5[-20251001]`, `@20251001`(Vertex), `anthropic.claude-haiku-4-5…-v1:0`(Bedrock), Haiku 3.5/3 ID | ✓ 플랫폼별 `claude-haiku-5-5` / `anthropic.claude-haiku-5-5` |
| H02 | error | `thinking.type: enabled`, `budget_tokens` | ✗ (adaptive + effort로 손수) |
| H03 | error/warn | `temperature`·`top_p`·`top_k`. `temperature: 1`과 `top_p: 0.99`만 warn(단독이면 허용) | ✗ |
| H04 | warn | messages 배열이 assistant 턴으로 끝나는 prefill(휴리스틱) | ✗ |
| H05 | error | `computer_20250124`, 베타 헤더 `computer-use-2025-01-24`, toolset과 함께 쓰인 `fine-grained-tool-streaming-2025-05-14` | ✓ API/Vertex→`computer_toolset_20260801`, Bedrock→`computer_20251124`+`computer-use-2025-11-24`. 제거 항목은 안내만 |
| H06 | error | Bedrock 경로의 `strict: true` 도구·`output_config.format` | ✗ |
| H07 | warn | `content[0].text`처럼 첫 블록을 답으로 가정 | ✗ |
| H08 | error | `code_execution_20250522`, 구 `text_editor_*` | ✓ |
| H09 | warn | `max_tokens` < 1024 (thinking 토큰 포함 + 토크나이저 30% 증가) | ✗ |
| H10 | info | 호출은 있는데 `refusal` 처리가 없는 파일 | ✗ |

2. 플랫폼은 파일마다 자동 감지한다(`AnthropicBedrock`·`bedrock-runtime`·`anthropic.claude-` → bedrock, `AnthropicVertex`·`@YYYYMMDD` → vertex, 나머지 api). `--platform`으로 강제할 수 있다.
3. 처음 e2e에서 cookbooks의 H03이 127건 나왔는데, 대부분 Sonnet/Opus 예제의 temperature였다. 그래서 `--scope haiku`(기본)를 두어 모델 ID·도구 버전(H01/H05/H08)은 항상 보고하되 파라미터 규칙은 파일에 "haiku"가 언급될 때만 보게 했다. 모델을 변수로 넘기는 코드는 `--scope all`로 전체를 본다.
4. `--fix`는 "old → new"가 명확한 치환(H01/H05/H08)만 적용하고, 헤더 제거·thinking 재설계처럼 문맥이 필요한 것은 건드리지 않는다. 치환 전후를 보려면 `--fix --dry-run`이 unified diff를 낸다.
5. 검증은 fixtures 5개(API·TS 도구·Bedrock·YAML 설정·이미 옮긴 코드)에 대한 `test.sh` 38건과, 공개 저장소 `anthropics/claude-quickstarts`·`claude-cookbooks`를 얕게 받아 실측하는 `e2e.sh`.

## 4. 사용법
```bash
python3 haiku_lint.py <경로>...                 # 사람용 보고. error가 있으면 exit 1 (CI 게이트로)
python3 haiku_lint.py src/ --json               # 기계용
python3 haiku_lint.py src/ --min-level error    # 400 확정만
python3 haiku_lint.py src/ --platform bedrock   # 플랫폼 강제
python3 haiku_lint.py src/ --scope all          # haiku 언급 없는 파일도 파라미터 규칙 적용
python3 haiku_lint.py src/ --fix --dry-run      # 모델 ID·도구 버전 치환 diff만
python3 haiku_lint.py src/ --fix                # 치환 적용
```
예시 출력(`fixtures/legacy_api.py`):
```
fixtures/legacy_api.py  (platform: api)
      7  H01  ERROR 400 확정  Claude API / Foundry / Platform on AWS Haiku 4.5 ID → `claude-haiku-5-5` (Haiku 5.5는 날짜 접미사·별칭 없음)
         │ model="claude-haiku-4-5-20251001",
         └ fix: claude-haiku-4-5-20251001 → claude-haiku-5-5
      9  H03  ERROR 400 확정  `temperature`은 Haiku 5.5에서 400. 제거하고 프롬프트로 유도
         │ temperature=0.2,
     11  H02  ERROR 400 확정  `budget_tokens`(수동 확장 사고)는 400. `thinking: {"type": "adaptive"}` + `output_config.effort`로
         │ thinking={"type": "enabled", "budget_tokens": 4000},
     15  H04  WARN  확인 필요  messages가 assistant 턴으로 끝나면(prefill) 400. user 턴으로 끝내고 구조화 출력·시스템 프롬프트로 대체
         │ {"role": "assistant", "content": "{\"label\":"},
     18  H07  WARN  확인 필요  응답이 `thinking` 블록으로 시작할 수 있음. `content[0]` 대신 `type == "text"`로 골라야
합계: error 4 · warn 3 · info 1  (파일 1개)
```
GitHub Actions에서는 `python3 haiku_lint.py . --min-level error` 한 줄이면 된다. 키 불필요.

## 5. 테스트 결과
`bash test.sh` (키·네트워크 없음):
```
[1] 전체 fixtures 린트 (텍스트)
  ✓ error가 있으면 exit 1
  ✓ 합계 줄 출력
[2] legacy_api.py — Claude API 규칙
  ✓ H01 검출
  ✓ H02 검출
  ✓ H03 검출
  ✓ H04 검출
  ✓ H07 검출
  ✓ H09 검출
  ✓ JSON에 platform 맵
  ✓ H01 fix 문자열(API)
  ✓ H03: temperature 0.2·top_k 둘 다 error
  ✓ H10: refusal 미처리 info
[3] legacy_tools.ts — 도구 버전·헤더
  ✓ H05 computer_20250124 검출
  ✓ H08 text_editor_20250124 검출
  ✓ API 플랫폼은 toolset으로 치환
  ✓ FGTS 헤더 제거 안내(toolset 동반)
  ✓ 구 베타 헤더 제거 안내
  ✓ H10 없음(refusal 처리 있음)
  ✓ H04 없음(user로 끝남)
[4] legacy_bedrock.py — 플랫폼 자동 감지
  ✓ bedrock 자동 감지
  ✓ H06 strict tool(Bedrock) 검출
  ✓ Bedrock ID 치환
  ✓ H07 없음(type으로 선택)
[5] --platform 강제
  ✓ Bedrock 강제 시 computer_20251124
  ✓ Bedrock 베타 헤더 치환
  ✓ --platform api면 H06 끔
[6] config.yaml — 허용값 경계
  ✓ temperature 1·top_p 0.99는 warn, Haiku 3.5 alias는 H01, max_tokens 8000은 통과
[7] migrated.py — 오탐 0
  ✓ 깨끗한 파일은 exit 0, 지적 없음
[8] --fix --dry-run / --fix
  ✓ dry-run은 unified diff 출력
  ✓ dry-run은 파일을 바꾸지 않음
  ✓ --fix: 모델 ID 치환
  ✓ --fix: 도구 버전 치환
  ✓ --fix: 제거 항목은 건드리지 않음(손으로)
  ✓ --fix: thinking/샘플링은 자동 수정 안 함
  ✓ fix 후 재린트에 H01 없음
[9] --min-level
  ✓ --min-level error는 error만
[10] --scope: haiku 언급 없는 파일은 파라미터 규칙 생략
  ✓ 기본 scope=haiku: Sonnet 전용 파일의 temperature는 무시
  ✓ --scope all이면 지적

통과 38 · 실패 0
```

`bash e2e.sh` — 공개 저장소 2개를 `--depth 1`로 받아 실측(네트워크만 필요, 모델 호출 없음. CI에서는 e2e 미실행):
```
== anthropics/claude-quickstarts
   파일 20개에서 지적 40건 · 규칙별: {'H01': 21, 'H04': 5, 'H05': 11, 'H08': 1, 'H10': 2}
   남아 있는 구 Haiku ID: {'claude-3-haiku-20240307': 3, 'claude-haiku-4-5-20251001': 8, 'anthropic.claude-haiku-4-5-20251001-v1:0': 1, 'claude-haiku-4-5@20251001': 1, 'claude-haiku-4-5': 8}
   - H01 customer-support-agent/README.md:119  { id: "claude-3-haiku-20240307", name: "Claude 3 Haiku" },
   - H01 customer-support-agent/README.md:128  const [selectedModel, setSelectedModel] = useState("claude-3-haiku-20240307");
   - H01 customer-support-agent/components/ChatArea.tsx:305  const [selectedModel, setSelectedModel] = useState("claude-haiku-4-5-20251001");
   - H01 customer-support-agent/components/ChatArea.tsx:319  { id: "claude-3-haiku-20240307", name: "Claude 3 Haiku" },
   - H01 customer-support-agent/components/ChatArea.tsx:320  { id: "claude-haiku-4-5-20251001", name: "Claude 4.5 Haiku" },
   - H01 autonomous-coding/prompts/app_spec.txt:105  - Claude Haiku 4.5 (claude-haiku-4-5-20251001)
== anthropics/claude-cookbooks
   파일 44개에서 지적 284건 · 규칙별: {'H01': 82, 'H03': 88, 'H04': 1, 'H07': 41, 'H09': 48, 'H10': 24}
   남아 있는 구 Haiku ID: {'claude-haiku-4-5': 56, 'anthropic.claude-haiku-4-5-20251001-v1:0': 3, 'claude-3-5-haiku-20241022': 4, 'claude-3-haiku-20240307': 19}
   - H01 CONTRIBUTING.md:121  - Latest Haiku model: `claude-haiku-4-5` (Haiku 4.5)
   - H01 .env.example:8  # Note: claude-haiku-4-5 is the latest Haiku model as of October 2025
   - H01 .env.example:9  CLAUDE_MODEL=claude-haiku-4-5
   - H01 CLAUDE.md:66  - Haiku: `claude-haiku-4-5`
   - H01 CLAUDE.md:72  - Haiku 4.5: `anthropic.claude-haiku-4-5-20251001-v1:0`
   - H01 tool_use/extracting_structured_json.ipynb:45  "MODEL_NAME = \"claude-haiku-4-5\""
```
10-10 기준 Anthropic 공식 예제 저장소에도 구 Haiku ID가 quickstarts 21곳, cookbooks 82곳 남아 있고, quickstarts의 computer-use 데모는 `computer_20250124`를 11곳에서 쓴다. Haiku 5.5로 모델만 바꾸면 그대로 400이 난다.

## 6. 한계와 다음 아이디어
- **정적 휴리스틱이다.** 모델을 변수·환경변수로 받는 코드는 어느 호출이 Haiku인지 모르므로 파일 단위 "haiku" 언급으로 범위를 정한다. 오탐·미탐이 모두 가능하고, prefill(H04)은 마지막 메시지가 assistant인지를 12줄 창에서 추정한다.
- **못 잡는 항목**: 대화 중 `system`/`tools`/이전 턴을 바꾸고 thinking 블록을 돌려보내는 경우(런타임 상태), 다른 계정으로 thinking 블록을 재생하는 경우, 이미지 토큰 증가, Priority Tier 미지원. 가이드의 11항목 중 9·8번이 여기 해당한다.
- **`--fix`는 문자열 치환이다.** 치환 후 H02/H03/H04는 사람이 고쳐야 하고, 가이드가 권하는 `thinking.display: "summarized"`나 effort 보정은 `/claude-api migrate`에 맡기는 편이 낫다. 이 도구는 "CI에서 빠르게 걸러내는 1차 게이트"가 목적이다.
- 다음: (1) 규칙을 JSON으로 빼서 Sonnet 4.5 → 5.5, Opus 5.5 가이드도 같은 엔진으로 (2) `claude -p --json-schema`로 H04·H07 같은 휴리스틱 지적을 Haiku 5.5에게 2차 판정시키는 `--judge` (3) PreToolUse 훅으로 묶어 `git commit` 전에 error가 있으면 막기(disaster-guard 패턴).

## 7. 출처
- Haiku 5.5 마이그레이션 가이드: https://platform.claude.com/docs/en/models/haiku-5-5/migration-guide
- API 릴리스 노트 2026-10-07 (Haiku 5.5 breaking changes): https://platform.claude.com/docs/en/release-notes/api
- Claude Haiku 5.5 발표: https://www.anthropic.com/claude-haiku-5-5
- Claude API 스킬 `migrate`: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/claude-api-skill
- computer use 도구 호환성: https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool
- e2e 대상 저장소: https://github.com/anthropics/claude-quickstarts , https://github.com/anthropics/claude-cookbooks
