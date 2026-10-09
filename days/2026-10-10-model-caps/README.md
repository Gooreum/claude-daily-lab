# model-caps — Models API로 만드는 모델 능력표와 스냅샷 diff

## 1. 무엇을 만들었나

Python CLI `model_caps.py`(표준 라이브러리만). `GET /v1/models` 응답을 읽어 모델마다 **line·lifecycle(퇴역 예정일)·출시일·입력/출력 토큰 한도·thinking adaptive/enabled/disabled 허용·effort 레벨·web_search·code_execution·structured_outputs·image·pdf·batch**를 Markdown 표 한 장으로 만든다.

- 기본은 dry-run: 키가 없으면 `sample-models.json`(문서의 응답 모양을 따른 설명용 예시, 실제 응답이 아님)을 읽는다.
- `--live --save snapshots/2026-10-10.json`: `ANTHROPIC_API_KEY`로 실제 호출. `after_id`로 끝까지 받고, `--lifecycle active,deprecated,retired`로 퇴역 모델까지 요청할 수 있다.
- `--diff <이전 스냅샷>`: 추가된 모델, 사라진 모델, 바뀐 필드(예: `lifecycle active → deprecated`, `code_execution ✗ → ✓`)만 출력한다.
- `--latest haiku`: 그 line의 active 모델 중 가장 최근 출시 id 한 줄. 라우터가 모델 id를 하드코딩하지 않게.
- `--only active --line opus`, `--json`.

## 2. 왜 만들었나

10월 1~6일 API 릴리스 노트로 Models API에 `line`, `capabilities.thinking.types.disabled`, `capabilities.server_tools`가 들어갔다. 10월 수집(`news/2026-10-october-all.md` 17번)의 현실 적용 1번 "모델 목록을 돌며 능력표를 자동 생성 → 문서가 아니라 API가 진실", 2번 "`line`으로 최신 haiku를 코드로", 4번 "매일 수집 때 모델 목록 diff를 소식으로"를 한 도구에 담았다. 특히 `thinking.types.disabled`는 "이 모델에 `thinking: disabled`를 보내면 400이 난다"를 요청 전에 알려 주는 필드라, 15번 항목의 Haiku 4.5→5.5 호환성 깨짐 목록을 코드로 예방하는 길이다.

## 3. 어떻게 만들었나

1. **스키마**: 문서 [List Models](https://platform.claude.com/docs/en/api/models/list)의 응답 필드를 그대로 `Row` dataclass로 옮겼다. `CapabilitySupport`는 `{"supported": bool}`이라 `_sup()`로 bool/None을 뽑고, `capabilities: null`(퇴역 모델)이나 모양이 다른 객체는 전부 `?`로 둔다. 응답이 깨져도 표는 나온다.
2. **effort 압축**: 지원 레벨이 연속이면 `low-max`, 중간(xhigh)이 빠지면 `low,medium,high,max`로 나열해 빠진 게 보이게 했다.
3. **정렬**: active → deprecated → retired, 같은 상태 안에서는 최신 출시가 위.
4. **페이지네이션**: `fetch_models(fetch, …)`가 `has_more`·`last_id`를 따라 `after_id`로 이어 받는다. `fetch`를 주입받아 테스트에서 HTTP 없이 돌린다. 최대 20페이지.
5. **diff**: id 집합 차로 추가·삭제, 공통 id는 `Row` 필드별 비교(`display_name`은 제외).
6. **키 처리**: `--live`인데 키가 없으면 아무것도 보내지 않고 exit 2. 키는 헤더로만 쓰고 저장하지 않는다. 스냅샷(`snapshots/*.json`)은 gitignore.

## 4. 사용법

```bash
cd days/2026-10-10-model-caps
python3 model_caps.py                                   # dry-run 표
python3 model_caps.py --diff sample-models-prev.json    # 예시 스냅샷 간 diff
python3 model_caps.py --latest haiku                    # claude-haiku-5-5

export ANTHROPIC_API_KEY=...                            # 실제 호출
python3 model_caps.py --live --lifecycle active,deprecated --save snapshots/$(date +%F).json
python3 model_caps.py --from snapshots/2026-10-11.json --diff snapshots/2026-10-10.json

bash test.sh     # unittest 19건 + dry-run 표 + diff + --latest (키 불필요)
bash e2e.sh      # 키가 있으면 live 표·스냅샷·전날 diff
```

## 5. 테스트 결과

`bash test.sh` (2026-10-10, Python 3.13):

```
== 1) python3 -m unittest
  Ran 19 tests in 0.008s
  OK
  ✅ unittest
== 2) dry-run 표
   | ### 모델 능력표 — sample-models.json (dry-run 샘플, API 응답이 아님)
   | | 모델 | line | 상태 | 출시 | 입력 | 출력 | thinking a/e/d | effort | web | code | JSON | img | pdf | batch |
   | | `claude-haiku-5-5` | haiku | active | 2026-10-01 | 200K | 64K | ✓✓✓ | low,medium,high,max | ✓ | ✗ | ✓ | ✓ | ✓ | ✓ |
   | | `claude-fable-5-1` | fable | active | 2026-09-18 | 1M | 128K | ✓✓✗ | low-max | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
  ✅ 표 8행
== 3) 스냅샷 diff (sample-models-prev.json → sample-models.json)
   | - ➕ 추가 `claude-3-7-sonnet-20250219`
   | - ➕ 추가 `claude-haiku-5-5`
   | - 🔁 `claude-haiku-4-5`: lifecycle active → deprecated; deprecated_at ? → 2026-10-01; retires_at ? → 2027-04-01
   | - 🔁 `claude-sonnet-5-5`: code_execution ✗ → ✓
  ✅ 추가·변경 감지
== 4) --latest haiku
  ✅ claude-haiku-5-5
== 결과: PASS
```

`bash e2e.sh`는 **돌리지 못했다**. 이 환경에 `ANTHROPIC_API_KEY`가 없고 Claude Code의 OAuth 로그인은 `/v1/models`에 쓸 수 없다. 출력:

```
ANTHROPIC_API_KEY 없음 — e2e 건너뜀 (bash test.sh는 키 없이 돈다)
```

처음 돌렸을 때 19건 중 1건이 깨졌다. `capabilities.thinking`이 dict가 아닌 값(문자열)일 때 `.get`에서 AttributeError. `_dict()` 헬퍼로 중첩 객체를 전부 감싸 고쳤다.

## 6. 한계와 다음 아이디어

- **실제 응답으로 검증하지 못했다.** 표의 값은 설명용 예시다. 키가 있는 환경에서 `bash e2e.sh`를 한 번 돌려 실제 필드 이름·값이 문서와 같은지 확인해야 한다. 특히 `line` 값 목록(`fable`, `mythos` 포함)과 `effort.xhigh`가 null로 오는 모델이 있는지.
- `context_management` 전략 3개와 `citations`는 Row에서 뺐다. 열이 14개를 넘으면 터미널에서 읽기 어렵다.
- 다음: 이 저장소의 아침 루틴에 `--live --save snapshots/$(date +%F).json` + 전날 diff를 넣어 "오늘 API에 새로 보이는 모델"을 news 항목으로 자동 생성. `--require claude-x thinking_disabled` 같은 프리플라이트 체크 명령으로 배포 전 400 예방. effort-race·cache-meter가 모델 id를 표에서 고르게 연결.

## 7. 출처

- Models API List Models 문서(응답 필드·lifecycle 필터): https://platform.claude.com/docs/en/api/models/list
- API 릴리스 노트 10-01 `line`, 10-05 `thinking.types.disabled`, 10-06 `server_tools`: https://platform.claude.com/docs/en/release-notes/api
- Python SDK lifecycle 필드·필터 (1.10.0~1.13.0): https://github.com/anthropics/anthropic-sdk-python/releases
- 10월 수집 17번·15번 항목과 다음 주제 3순위: ../../news/2026-10-october-all.md
