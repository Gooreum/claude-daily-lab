# review-gate

## 1. 무엇을 만들었나
CLI 스크립트 하나(`review_gate.py`, 표준 라이브러리만). `gate`는 GitHub PR의 `Claude Code Review` 체크런을 읽어 Important(🔴) 개수 등이 기준을 넘으면 실패 종료 코드를 돌려주는 병합 관문이다. 개수 줄이 없거나 리뷰가 안 끝났으면 "0개"가 아니라 **판정 없음(exit 3)**으로 따로 처리한다. `lint`는 `REVIEW.md`가 Important 정의·Nit 상한·제외 범주를 갖췄는지, 그리고 베이스 브랜치에 병합돼 있는지(리뷰는 PR 자신의 변경분을 읽지 않는다) 점검한다.

## 2. 왜 만들었나
- 소식: [Code Review is now generally available (2026-10-15)](https://claude.com/resources/articles/code-review-is-now-generally-available) — 리뷰가 약 20분에서 6~10분으로 빨라지고 Quick·Standard·Deep 깊이를 고를 수 있다.
- 문서([Read and request reviews](https://code.claude.com/docs/en/code-review-pull-requests))에 따르면 리뷰는 PR을 승인하지도 막지도 않고 체크런도 실패로 끝나지 않는다. 병합 관문을 원하면 체크런 본문 마지막 줄의 `bughunter-severity` 주석을 직접 읽어야 하는데, 그 줄이 없는 경우(실패·타임아웃·교체된 리뷰)를 0개로 오해하면 조용히 통과하는 사고가 난다. 이 함정과 `REVIEW.md` 병합 순서 함정이 "직접 만들어볼 만하다"고 판단한 이유다.

## 3. 어떻게 만들었나
1. 문서 세 쪽(code-review-pull-requests, code-review-customize, code-review)에서 동작 규칙을 추렸다: 체크런 이름, 등급 키(`normal`=Important, `nit`, `pre_existing`), "개수 줄이 없으면 판정 없음", `REVIEW.md`는 기본/베이스 브랜치 사본만 읽음.
2. 종료 코드를 네 갈래로 나눴다(0 통과·1 초과·2 입력 오류·3 판정 없음). CI에서 "실패"와 "확인 못 함"을 구분하려는 설계다. `--on-no-verdict pass`로 완화할 수 있다.
3. 같은 이름의 체크런이 여럿이면(재실행) 완료 시각이 가장 늦은 것을, 본문에 주석이 여러 번 나오면 마지막 것을 쓴다. 본문에 따옴표로 인용된 주석에 속지 않기 위해서다.
4. `--repo/--sha` 모드는 `gh api`로 목록을 받고, 목록의 `output.text`가 비어 있으면 문서의 두 번째 호출(`check-runs/ID`)로 한 번 더 받는다. 테스트는 가짜 `gh`를 PATH 앞에 둬서 이 경로 전체를 태운다.
5. 막힌 지점: 처음 만든 Nit 상한 정규식이 문서 예시 문장("Report at most **five** Nits")을 못 잡아 테스트가 실패했다. 숫자 단어(one~ten)와 "Cap nits at 5", "limited to 5" 형태를 추가해 고쳤다.
6. 가정 하나: 개수 줄이 없을 때 제목 "Code review found no issues"를 0개로 볼지는 문서에 규정이 없어, 기본은 판정 없음으로 두고 `--trust-title`을 켰을 때만 0개로 본다.

## 4. 사용법
```bash
# 병합 관문 (CI의 PR 잡에서). 인증은 gh가 처리한다
python3 review_gate.py gate --repo OWNER/REPO --sha "$PR_HEAD_SHA" --max-nit 5
# 저장해 둔 JSON으로 / stdin으로
python3 review_gate.py gate --file check-runs.json --max-important 0
gh api repos/OWNER/REPO/commits/SHA/check-runs | python3 review_gate.py gate --file - --json
# 부를 gh 명령만 보기
python3 review_gate.py gate --repo OWNER/REPO --sha SHA --dry-run

# REVIEW.md 점검 (루트·하위 REVIEW.md 모두). --base로 병합 여부, --strict면 경고도 실패
python3 review_gate.py lint . --base origin/main
```
옵션: `--max-important N`(기본 0) · `--max-nit N` · `--max-pre-existing N` · `--on-no-verdict pass|fail` · `--trust-title` · `--json`.

예시 출력:
```
$ python3 review_gate.py gate --file tests/fixtures/important.json
[FAIL] Important 2 · Nit 1 · Pre-existing 0
  기준 초과: Important 2 > 0
(exit 1)
$ python3 review_gate.py gate --file tests/fixtures/no_line.json
[NONE]
  본문에 bughunter-severity 줄이 없다. 0개가 아니라 판정 없음으로 본다(실패·타임아웃·교체된 리뷰일 수 있다)
(exit 3)
```

## 5. 테스트 결과
`bash test.sh` (유닛 17개 + 종료 코드·stdin·가짜 gh·임시 git 저장소 시나리오). 모델·네트워크 불필요라 `e2e.sh`는 없다. 실제 GitHub의 Code Review 체크런으로는 돌려 보지 못했다(Team/Enterprise 조직과 GitHub 저장소가 필요).
```
test_general_and_open_ended (test_review_gate.LintTests.test_general_and_open_ended) ... ok
test_good_file_clean (test_review_gate.LintTests.test_good_file_clean) ... ok
test_korean_cap (test_review_gate.LintTests.test_korean_cap) ... ok
test_missing_pieces (test_review_gate.LintTests.test_missing_pieces) ... ok

----------------------------------------------------------------------
Ran 17 tests in 0.026s

OK
OK: Important 2개 → 실패 (exit 1)
OK: 발견 없음 → 통과 (exit 0)
OK: 개수 줄 없음 → 판정 없음 (exit 3)
OK: 판정 없음을 --on-no-verdict pass로 허용 (exit 0)
OK: 진행 중 → 판정 없음 (exit 3)
OK: --file 없이 호출 → 사용법 오류 (exit 2)
OK: 없는 파일 → 입력 오류 (exit 2)
OK: stdin + --json
OK: 가짜 gh로 --repo 경로 (목록 → 단건 조회, Important 2 → exit 1)
OK: --dry-run은 gh를 부르지 않고 명령만 출력
OK: lint — 병합된 REVIEW.md 통과
OK: lint — 미병합 services/billing/REVIEW.md → R030 오류 (exit 1)
ALL OK
```

## 6. 한계와 다음 아이디어
- **실제 체크런 미검증.** 입력 형식은 문서의 `gh api` 예시와 `bughunter-severity` 설명에 맞춘 픽스처다. 실제 응답이 다르면(예: 목록 응답에 `output.text` 필드 구성) 고쳐야 한다. 이 경로는 `output.text`가 비면 단건 조회로 보완해 뒀다.
- 문서상 주석 키는 `normal`·`nit`·`pre_existing`뿐이다. 새 키가 생기면 무시한다.
- `lint`는 정규식 휴리스틱이라 영어·한국어 일부 표현만 안다. 브랜치 보호 설정(문서의 "보호된 기본 브랜치" 조건)은 확인하지 않는다.
- 다음: GitHub Actions 예제 워크플로 추가, `pull_request` 이벤트에서 리뷰 완료까지 폴링(`--wait`), 등급 키 변경 시 경고.

## 7. 출처
- https://claude.com/resources/articles/code-review-is-now-generally-available
- https://code.claude.com/docs/en/code-review
- https://code.claude.com/docs/en/code-review-pull-requests
- https://code.claude.com/docs/en/code-review-customize
