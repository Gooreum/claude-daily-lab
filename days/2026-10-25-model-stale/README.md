# model-stale — 저장소에 박힌 Claude 모델 ID의 수명주기 점검기

## 1. 무엇을 만들었나
코드·설정·노트북·`.env.example`에 적힌 Claude 모델 ID를 훑어서 **이미 퇴역했는지, 퇴역 예정이면 며칠 남았는지, 같은 계열에 더 새 모델이 있는지**를 날짜 기준으로 보고하는 CLI 스크립트(`model_stale.py`, Python 표준 라이브러리만). 직접 API ID뿐 아니라 Bedrock(`global.anthropic.…-v1:0`, 접미사 없는 새 형식)과 Vertex(`…@20251001`) 표기를 같은 모델로 정규화한다. 모델 표(`models.json`)는 공식 "Model deprecations" 페이지에서 `--import live`로 갱신한다. 키·모델 호출은 필요 없다.

| 규칙 | 수준 | 잡는 것 |
|---|---|---|
| M01 | error | 퇴역(Retired)한 모델 — 요청이 실패한다 |
| M02 | error / warn | Deprecated 모델: 퇴역일이 지났으면 error, 남았으면 warn(D-n) |
| M03 | warn | Active지만 "가장 이른 퇴역일"(Not sooner than)이 지났거나 `--warn-days`(기본 90) 안 |
| M04 | info | 같은 계열에 더 새 모델이 있음 (M01~M03이 이미 걸린 토큰은 접는다) |
| M05 | warn | 표에 없는 `claude-*` 모델 ID (표보다 새 모델이거나 버전 오타) |
| M06 | info | 날짜가 박힌 ID인데 날짜 없는 별칭이 있음 |

## 2. 왜 만들었나
계기: [claude-cookbooks 커밋 #924 "Bump cookbook defaults to Opus 5.5, Sonnet 5.5 and Fable 5.1"](https://github.com/anthropics/claude-cookbooks/commit/bfe50e59dbb4f5546a0af9ca36ebb77e637c9ce1) (`news/2026-10-25.md` 1번). 쿡북은 116개 파일의 기본 모델을 바꾸면서 `validate_notebook.py`에 최신 / 구형(서비스 중) / 퇴역 세 표를 만들고, 구형은 경고·퇴역은 차단으로 나눴다. 같은 날 공식 퇴역 표를 보면 `claude-sonnet-4-5-20250929`는 2026-11-30 퇴역(오늘 기준 D-36)이고, `claude-haiku-4-5`의 "가장 이른 퇴역일"(2026-10-15)은 이미 지났다. 이 저장소의 `haiku-migrate-lint`는 Haiku 한 계열의 *전환*만 보고, `model-caps`는 API 응답을 표로 만들 뿐이라 "내 코드의 어떤 ID가 며칠 뒤 죽는가"를 날짜로 답하는 도구가 없었다.

## 3. 어떻게 만들었나
1. 공식 퇴역 페이지(`model-deprecations.md`)의 "Model status" 표와 "Deprecation history"의 대체 모델 표를 읽어 `models.json` 구조(상태·Deprecated 날짜·퇴역일·"not sooner than" 여부·문서 권장 대체 모델)를 정했다. 계열별 "최신"은 표에 따로 적지 않고 **Active인 모델 중 가장 높은 (major, minor)** 로 계산한다 — 새 모델이 표에 들어오면 규칙이 자동으로 따라간다.
2. ID 정규식: `claude-(opus|sonnet|haiku|fable|mythos)-<1~2자리 숫자 0~2개>` 뒤에 날짜(`-20250929` / `@20250929`) · `-latest` · `-preview`, 앞에 리전·`anthropic.`, 뒤에 `-v1:0`. `claude-code`·`claude-agent-sdk`는 계열 이름이 없어 걸리지 않는다. `\d{1,2}`로 버전을, `\d{8}`로 날짜를 구분해 `claude-opus-4-1-20250805`와 `claude-opus-4-20250514`가 서로 섞이지 않게 했다.
3. 날짜 있는 ID에서 **날짜 없는 별칭과 `-latest` 별칭을 자동 파생**하고, 파생으로 안 되는 `claude-opus-4-0` · `claude-sonnet-4-0`만 `extra_aliases`에 적었다.
4. 판정 수준은 쿡북의 "경고 / 차단" 분리를 날짜로 확장했다. 같은 ID가 11-30 전에는 warn, 뒤에는 error가 되므로 `--today`로 시계를 고정해 테스트한다. 문서가 권하는 대체 모델이 계열 최신과 다르면(예: Opus 4.1 → 문서는 4.8, 최신은 5.5) 둘 다 보여 준다.
5. 거짓 양성 장치: 같은 줄이나 바로 윗줄에 `model-stale: allow`를 쓰면 건너뛴다(평가 결과 재현용 핀 등). `--exclude` glob(파일·폴더 이름 모두), `--ignore M04,M06`, NUL 바이트 파일·2MB 초과·`node_modules`·`.git` 제외.
6. 막힌 곳: `urllib`로 공식 페이지를 받으면 403이 나왔다(`curl`은 200). `User-Agent` 헤더를 달아 해결했다. 또 argparse가 옵션 사이에 낀 경로를 못 받아 첫 테스트가 실패했고 `parse_intermixed_args`로 고쳤다.

## 4. 사용법
```bash
cd days/2026-10-25-model-stale
python3 model_stale.py <폴더|파일>...            # 기본: error가 있으면 exit 1
python3 model_stale.py . --summary               # 모델 ID별 요약 표
python3 model_stale.py . --min-level warn        # CI에서 warn부터 실패
python3 model_stale.py . --warn-days 30 --ignore M04,M06
python3 model_stale.py . --exclude "CHANGELOG*" --exclude archive
python3 model_stale.py --import live             # 공식 페이지로 models.json 갱신(네트워크)
python3 model_stale.py --import page.md --table my.json   # 저장해 둔 페이지로
```
출력 예 (`--today 2026-10-25`, `fixtures/app`):
```
error M01 fixtures/app/chat.py:6  claude-3-5-sonnet-20241022  퇴역한 모델 (2025-10-28) — 요청이 실패한다 → claude-sonnet-5-5
warn  M02 fixtures/app/chat.py:10  claude-sonnet-4-5  Deprecated — 2026-11-30 퇴역(D-36) → claude-sonnet-5-5
warn  M03 fixtures/app/chat.py:16  claude-haiku-4-5  가장 이른 퇴역일(2026-10-15)이 지났다 — 아직 서비스 중이지만 언제든 퇴역할 수 있다 → claude-haiku-5-5
info  M04 fixtures/app/chat.py:13  claude-opus-4-8  같은 계열에 더 새 모델이 있다 → claude-opus-5-5
```
허용 표시: `PINNED = "claude-3-opus-20240229"  # model-stale: allow 평가 결과 재현용`

## 5. 테스트 결과
`bash test.sh` (키·네트워크 없음):
```
[1] 종료 코드
  ✓ error가 있으면 exit 1
  ✓ 최신 ID·비모델 이름만 있으면 exit 0
  ✓ --min-level info + M01 끔 → warn/info로 exit 1
  ✓ M01 끄면 warn만 남아 exit 0
  ✓ 없는 경로는 exit 2
  ✓ 모르는 규칙 --ignore는 exit 2
  ✓ 잘못된 --today는 exit 2
[2] chat.py — 규칙별 판정
  ✓ M01:6:error
  ✓ M01:7:error
  ✓ M02:10:warn
  ✓ M04:13:info
  ✓ M03:16:warn
  ✓ M03:19:warn
  ✓ M06:19:info
  ✓ M05:22:warn
  ✓ M03이 있으면 M04는 접는다
  ✓ 줄 25 통과(최신·허용 표시)
  ✓ 줄 28 통과(최신·허용 표시)
  ✓ 줄 30 통과(최신·허용 표시)
[3] 플랫폼 형식 정규화
  ✓ bedrock.ts M02:1:warn
  ✓ bedrock.ts M03:2:warn
  ✓ bedrock.ts M03:3:warn
  ✓ bedrock.ts M01:5:error
  ✓ 리전 접두 최신 ID 통과
  ✓ .env.example 점 파일도 스캔
  ✓ claude-code는 모델 ID가 아님
[4] 날짜 의존 — 같은 파일, 다른 기준일
  ✓ 11-30 전: M02 warn
  ✓ 11-30 뒤: M02 error
  ✓ 퇴역일이 90일보다 먼 날엔 M03 없음
  ✓ --warn-days 10이면 D-30은 M03 아님
[5] 파일 처리
  ✓ NUL 바이트 파일은 건너뜀
  ✓ node_modules 건너뜀 · --exclude glob
  ✓ --exclude는 폴더 이름도 건너뜀
  ✓ --summary 표
[6] 표 낡음 경고
  ✓ 45일 넘으면 갱신 경고
  ✓ 신선한 표엔 경고 없음
[7] --import (공식 페이지 → 표)
  ✓ 같은 페이지를 다시 가져오면 변화 없음
  ✓ 새 모델 1 추가 · 상태 변경 1 감지
  ✓ 갱신 표 반영: Retired → M01, 새 최고 버전은 통과
  ✓ 표를 못 찾는 페이지는 exit 2

통과 40 · 실패 0
```
`bash e2e.sh` (공식 페이지 실제 수신 + 이 저장소 스캔, 2026-10-24 UTC 실행. 긴 줄은 줄임):
```
[1] live import\n표 갱신: 추가 36 ['claude-fable-5-1', 'claude-mythos-5-1', 'claude-fable-5', 'claude-mythos-5', 'claude-m ...]\n✓ 모델 36개, 필수 ID 포함\n[2] 이 저장소 스캔 (live 표, 모든 fixtures 폴더와 이 도구 폴더 제외)\n| 모델 ID | 최고 수준 | 건수 | 파일 수 |\n|---|---|---|---|\n| `claude-3-haiku-20240307` | error | 6 | 2 |\n| `claude-3-7-sonnet-20250219` | error | 6 | 3 |\n| `claude-3-5-haiku-20241022` | error | 1 | 1 |\n| `claude-3-5-haiku` | error | 1 | 1 |\n| `claude-3-5-haiku@20241022` | error | 1 | 1 |\n| `claude-3-5-haiku-latest` | error | 1 | 1 |\n| `claude-haiku-4-5` | warn | 18 | 8 |\n| `claude-haiku-4-5-20251001` | warn | 18 | 2 |\n| `anthropic.claude-haiku-4-5-20251001-v1:0` | warn | 4 | 2 |\n| `claude-sonnet-4-5` | warn | 3 | 2 |\n| `claude-haiku-55` | warn | 3 | 2 |\n| `claude-haiku-4-5@20251001` | warn | 2 | 2 |\n| `anthropic.claude-haiku-4-5` | warn | 1 | 1 |\n| `claude-haiku-5-5-20261007` | warn | 1 | 1 |\n| `claude-opus-5-5-20261001` | warn | 1 | 1 |\n| `claude-sonnet-55` | warn | 1 | 1 |\n| `claude-sonnet-45` | warn | 1 | 1 |\n| `claude-sonnet-4-5-20250929` | warn | 1 | 1 |\n| `claude-opus-5` | info | 5 | 5 |\n| `claude-fable-5` | info | 1 | 1 |\n| `claude-sonnet-5` | info | 1 | 1 |\n\nerror 16 · warn 45 · info 16 (기준일 2026-10-24, 표 2026-10-24)
```
실제 저장소에서 나온 것: 다른 날짜 폴더의 `days/2026-10-24-cache-break/cache_break.py:28`이 `claude-haiku-4-5`(가장 이른 퇴역일 지남, M03)를 쓴다. 다른 날짜 폴더는 수정하지 않는 규칙이라 고치지 않고 기록만 한다. error들은 `haiku-migrate-lint`·`model-caps`가 일부러 둔 구형 ID(퇴역 모델 입력 예) 코드·샘플이고, `claude-sonnet-55`·`claude-haiku-55`는 `news/2026-10-10.md`가 "5.5" 표기를 설명한 문장 조각(오탐 — `--exclude news`로 끄거나 `model-stale: allow`).

## 6. 한계와 다음 아이디어
- 표는 **문서에 적힌 날짜**의 사본이다. 45일 넘으면 경고를 내지만 `--import live`를 부르는 것은 사람/CI의 몫이다. 퇴역 날짜는 "Not sooner than"이라 실제 퇴역은 더 늦을 수 있다.
- 모델 이름이 아닌 문장("Claude Sonnet 4.5")과 `claude-sonnet-45` 같은 변형은 잡지 않는다. ID 안에 문자열을 이어 붙여 만드는 코드(`f"claude-{fam}-{ver}"`)도 정적으로는 못 본다.
- 계열(opus/sonnet/haiku/fable/mythos)이 이름에 들어가지 않는 새 모델이 나오면 정규식에 계열을 추가해야 한다. 버전이 두 자리를 넘는 ID(예: `-10`)는 아직 다루지 않는다.
- 플랫폼별 퇴역 일정이 다른 점(Bedrock·Google 관리형은 자체 일정)은 반영하지 않는다. 표의 날짜는 Anthropic 운영 플랫폼 기준이다.
- 다음: `--fix`로 구형 → 최신 치환(다만 샘플링 파라미터 같은 동반 변경은 `apiver-lint`·`haiku-migrate-lint`가 담당), Usage CSV 내보내기와 대조하는 모드, PR 코멘트용 Markdown 출력.

## 7. 출처
- https://github.com/anthropics/claude-cookbooks/commit/bfe50e59dbb4f5546a0af9ca36ebb77e637c9ce1 — 쿡북 기본 모델 교체와 3단계 표
- https://platform.claude.com/docs/en/about-claude/model-deprecations — 모델 상태·퇴역일·대체 모델 (`fixtures/deprecations-2026-10-24.md`가 그날 `.md` 사본)
- https://platform.claude.com/docs/en/about-claude/model-deprecations.md — `--import live`가 받는 주소
