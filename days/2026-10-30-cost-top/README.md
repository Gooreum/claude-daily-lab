# cost-top

## 1. 무엇을 만들었나
Usage and Cost Analytics API(베타)의 `cost`·`usage` 엔드포인트를 불러 조직의 비용·토큰을 `group_by` 기준으로 모으고, 상위 소비자 표와 시간 버킷별 합계, 급증 구간을 찍는 CLI(`cost_top.py`, 표준 라이브러리만)다. 요청을 보내기 전에 문서의 제약(31일, 1m 버킷은 24시간, 그룹 5개, 시작일 범위)을 로컬에서 검사하고, 응답의 `data_refreshed_at` 이후 구간은 "부분 데이터"로 표시해 급증 판정에서 뺀다. 키가 없어도 `--dry-run`으로 요청 URL을 보고 합성 샘플 보고서를 볼 수 있다.

## 2. 왜 만들었나
2026-10-29 API 릴리스 노트: [Usage and Cost Analytics API 베타](https://platform.claude.com/docs/en/release-notes/api). 기존 Usage and Cost API가 레거시가 되고 새 엔드포인트가 모델·워크스페이스·API 키·사용자별 비용을 한 구조(`group`/`cost`)로 준다. 이 저장소의 비용 도구(spend-gate·cache-break·cache-meter)는 모두 로컬 세션 기준이라 조직 단위 숫자를 읽는 도구가 비어 있었다. 응답에 함정이 많다는 점(센트 단위 십진 문자열, 31일 한도, 늦게 채워지는 데이터)도 직접 만들어 볼 이유였다. news/2026-10-30.md 1번.

## 3. 어떻게 만들었나
1. 문서(`manage-claude/usage-cost-analytics-api`)를 읽고 제약과 응답 모양을 뽑았다: `starting_at` 포함·`ending_at` 제외, 31일, `time_bucket_width` 사용 시 `ending_at` 필수, `1m`은 24시간, `group_by[]` 최대 5개(비용 전용 `cost_type`·`token_type`은 제외), 금액은 센트 문자열(`"41280.000000"`=$412.80).
2. `validate()`가 위반 목록을 모아 한 번에 돌려준다. 서버가 거절하기 전에 "기간을 나눠 부르라" 같은 해결책까지 말해 준다.
3. 금액은 `Decimal`로만 더한다(부동소수점 오차 방지). 그룹 이름은 `group_by` 순서로 `model | workspace_id`처럼 잇고, `actor` 객체는 `type:id:email`로 접는다.
4. 급증은 "데이터가 다 찬 버킷의 중앙값 × `--spike-factor`(기본 3) 이상이고 `--spike-min` 이상"으로 정했다. 갱신 시각 이후 버킷은 일부만 채워졌을 수 있어 제외한다. 이 기준은 내가 정한 것이며 문서에 있는 규칙이 아니다.
5. 테스트는 `fake_server.py`(127.0.0.1에서만 여는 가짜 API)로 실제 HTTP 왕복을 시험한다: 두 쪽 페이지네이션, 헤더, 401, 끝나지 않는 `has_more`, 연결 거부.
- 막힌 지점: 문서의 서술에는 다음 쪽을 요청하는 쿼리 파라미터 이름이 없었다(SDK가 감춘다). 응답의 `next_page` 토큰을 `page=`로 돌려보내는 Anthropic의 일반 규칙을 따랐다. **이 부분은 실제 API로 확인하지 못했다** (6절).

## 4. 사용법
```bash
# 키 없이: 요청 URL을 만들어 검사하고 합성 샘플로 보고서를 그린다
python3 cost_top.py cost --days 8 --bucket 1d --group-by model --dry-run

# 실제 조회 (Admin API 키 필요, Console 조직). 최근 7일, 사람별 비용 상위 5
export ANTHROPIC_ADMIN_KEY=...        # 없으면 ANTHROPIC_API_KEY를 읽는다
python3 cost_top.py cost --days 7 --group-by actor --filter products=claude_code --top 5

# 시간 버킷 + 급증이 있으면 종료 코드 1 (크론·CI용)
python3 cost_top.py cost --days 7 --bucket 1d --fail-on-spike

# 토큰 사용량, 저장해 둔 응답 재생
python3 cost_top.py usage --days 7 --group-by api_key_id --order-by requests
python3 cost_top.py cost --days 5 --bucket 1d --input saved.json
```
`--dry-run` 출력 일부:
```
[dry-run] GET https://api.anthropic.com/v1/organizations/analytics/cost?starting_at=2026-10-16T00:00:00Z&ending_at=2026-10-24T00:00:00Z&time_bucket_width=1d&group_by[]=model&limit=100
## 비용 합계: $3,699.80  (그룹 2개, 기준 model)
| 1 | claude-opus-5-5 | $3,332.80 | $4,166.00 | 20% | - | 90.1% |
- 2026-10-22T00:00:00Z  $2,208.00 ← 급증
🔺 2026-10-22T00:00:00Z: $2,208.00 — 중앙값의 4.4배
```
종료 코드: 0 정상 · 1 급증(`--fail-on-spike`) · 2 요청·입력 오류 · 3 사용법 오류. 키는 출력에 나오지 않는다(오류 본문에서도 가린다).

## 5. 테스트 결과
`bash test.sh` (이 폴더, 키·모델·외부 네트워크 없음. CI에서는 e2e 미실행):
```
[1] 요청 검증 — 문서의 제약을 보내기 전에 잡는다
  ✅ 32일 범위 거부 (exit=2)
  ✅ 31일은 통과 (exit=0)
  ✅ 1m 버킷 24시간 초과 거부 (exit=2)
  ✅ 버킷은 ending_at 필요 (exit=2)
  ✅ group_by 6개 거부 (exit=2)
  ✅ cost_type은 5개에 안 센다 (exit=0)
  ✅ usage에 cost_type 거부 (exit=2)
  ✅ 2026년 이전 시작 거부 (exit=2)
  ✅ 365일 넘은 시작 거부 (exit=2)
  ✅ order_by=time은 버킷 필요 (exit=2)
  ✅ usage order_by 오타 거부 (exit=2)
  ✅ 끝이 시작보다 앞 (exit=2)
  ✅ 날짜 형식 오류 (exit=2)
  ✅ 기간 인자 없음 (exit=2)
  ✅ 잘못된 엔드포인트 (exit=3)
  ✅ 필터 값 101개 거부 (exit=2)
[2] dry-run — 키 없이 URL을 만들고 합성 샘플로 보고서를 그린다
  ✅ URL에 group_by[]=model
  ✅ URL에 시작·끝(오늘 00:00Z 기준)
  ✅ 필터가 models[]= 반복으로 변환
  ✅ 베타 헤더 이름을 보여 준다
  ✅ 샘플임을 밝힌다
  ✅ 센트 문자열을 달러로 환산 (50380센트=503.80달러)
  ✅ dry-run usage는 거부 (exit=2)
  ✅ 키 없으면 안내하고 실패 (exit=2)
[3] 가짜 서버로 실제 HTTP 왕복 — 페이지네이션·헤더·오류
  ✅ 2쪽을 이어 받아 합계 153.00달러
  ✅ opus는 쪽을 가로질러 150.50달러
  ✅ 할인율 계산 (정가 대비)
  ✅ 종료 코드 0
  ✅ 서버가 요청 2번을 받음
  ✅ 첫 요청에는 page 없음
  ✅ 둘째 요청이 next_page 토큰을 보냄
  ✅ x-api-key 헤더 전송
  ✅ 베타·버전 헤더 전송
  ✅ 경로가 /v1/organizations/analytics/cost
  ✅ 출력에 키가 나오지 않음
  ✅ 401 → exit 2, 서버 메시지 표시
  ✅ 오류 출력에 키가 나오지 않음
  ✅ has_more가 끝나지 않으면 100쪽에서 중단
  ✅ 연결 거부 → exit 2
  ✅ ANTHROPIC_API_KEY로 폴백
[4] 저장한 응답 재생 — 급증·부분 데이터·갱신 시각
  ✅ 10-04 급증(중앙값의 8배 넘게) 표시
  ✅ 갱신 시각 이후(10-05) 버킷은 부분
  ✅ 부분 버킷은 급증 판정에서 제외
  ✅ 급증만으로는 exit 0
  ✅ --fail-on-spike면 exit 1 (exit=1)
  ✅ --spike-min이 크면 급증 아님 (exit=0)
  ✅ --spike-factor 20이면 급증 아님 (exit=0)
  ✅ data_refreshed_at null이면 경고 (exit=0)
  ✅ 버킷 2개면 급증 판정 안 함 (exit=0)
[5] 집계 세부 — usage, actor 객체, priority 주의, JSON
  ✅ usage: 토큰 합계 600
  ✅ actor 객체를 type:id:email로 표시
  ✅ actor null은 (없음)
  ✅ 요청 수 합산
  ✅ priority 행에 약정 주의 문구 (exit=0)
  ✅ --json이 파싱된다
  ✅ 쪽 배열 입력, 빈 데이터 (exit=0)
  ✅ --top이 줄 수를 자르고 나머지 표시 (exit=0)

통과 57 · 실패 0
```
실제 Anthropic API는 호출하지 않았다(Admin 키 없음). 서버 쪽 동작은 문서에 적힌 응답 모양을 따라 만든 가짜 서버로만 확인했다.

## 6. 한계와 다음 아이디어
- **실제 API로 확인하지 못했다.** 다음 쪽 파라미터 이름(`page`)은 추정이고, `actor` 객체의 필드 이름(`type` 외)도 문서 예시에 없어 `id`·`name`·`email`을 있으면 쓰는 방식으로 짰다. 실제 응답과 다르면 라벨만 달라진다.
- `--dry-run`의 샘플은 `cost`만 있다. `usage`는 `--input`으로 저장한 응답을 읽는다.
- 급증 기준(중앙값 × 3)은 단순하다. 주말·월초 패턴이 있는 조직은 `--spike-factor`를 올려야 한다. 비어 있는 버킷은 중앙값 계산에서 빠진다.
- 31일을 넘는 기간은 사용자가 나눠 불러야 한다(자동 분할은 다음 아이디어). 이전 달 대비 증감, 워크스페이스 예산 대비 경고, Enterprise `read:analytics` 키 경로 시험도 남았다.
- 레거시 Usage and Cost API 응답을 새 모양으로 바꿔 주는 변환기는 만들지 않았다.

## 7. 출처
- https://platform.claude.com/docs/en/manage-claude/usage-cost-analytics-api
- https://platform.claude.com/docs/en/release-notes/api
- https://code.claude.com/docs/en/changelog
- https://github.com/anthropics/claude-quickstarts/commit/1a18c340ca42b9137d991637afe867bdcf70a9ce (세션당 비용 상한 모델 참고)
