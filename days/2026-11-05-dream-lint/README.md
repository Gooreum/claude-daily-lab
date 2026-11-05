# dream-lint

## 1. 무엇을 만들었나
Claude의 파일 기억 폴더(`MEMORY.md` 색인 + 프론트매터가 있는 `.md` 파일들)를 규칙으로 점검하는 **CLI 스크립트**(`dream_lint.py`, 표준 라이브러리만 사용)다. 색인이 없는 파일을 가리키거나, 색인에 안 올라간 기억, 필수 항목 누락, 잘못된 유형, `feedback`·`project`의 `**Why:**`/`**How to apply:**` 누락, 상대 날짜, 비슷한 설명의 중복, 비밀값 패턴을 찾는다. 모델·키·네트워크는 쓰지 않는다.

## 2. 왜 만들었나
- 소식: claude-cookbooks에 **dreaming 쿡북**이 올라왔다(2026-11-04). 에이전트가 끝낸 세션 기록을 밤마다 위키 형태의 메모리 저장소로 정리하는 예제다. (news/2026-11-05.md 2번)
- 정리는 모델에 맡기더라도, 깨진 링크·색인 누락·비밀값 같은 문제는 규칙으로 먼저 잡는 편이 싸고 정확하다. 정리 에이전트가 밤새 돌기 전에(또는 후에) 기계 검사를 한 번 끼우는 용도다. 루트 README에 기억 점검 결과물이 아직 없어서 골랐다.

## 3. 어떻게 만들었나
1. 점검 항목을 "모델이 필요 없는 것"으로만 한정했다. 의미 판단(어느 기억이 낡았나)은 하지 않는다.
2. 프론트매터는 `name`, `description`, `metadata.type` 세 항목만 필요해서 YAML 라이브러리 없이 한 단계 중첩만 읽는 작은 파서를 직접 썼다. 의존성이 없어야 폴더 하나로 끝난다.
3. 심각도를 셋으로 나눴다. **오류**(읽기 깨짐·비밀값), **경고**(품질), **참고**(`[[링크]]`의 대상이 아직 없는 것은 "쓸 거리로 남긴 것"일 수 있어 오류가 아님). 종료 코드 0/1/2/3으로 cron·CI에서 쓴다.
4. 중복 판정은 설명 문장의 단어 집합 자카드 유사도(기본 0.6 이상)다. 단순하지만 `user-a`/`user-b` 같은 복제를 잡는다.
5. 비밀값 패턴 문자열이 저장소의 푸시 전 검사에 걸리므로 코드에서는 조각으로 조립하고, 테스트 fixture의 비밀값은 `test.sh`가 임시 폴더에서 만들어 쓴다. 출력에는 비밀값 원문을 찍지 않는다.
6. 이 저장소 지침상 별도 개발 워크플로 없이 Write/Bash로 만들고 `test.sh`로 검증했다.

## 4. 사용법
```bash
python3 dream_lint.py <기억 폴더>              # 사람이 읽는 출력
python3 dream_lint.py <기억 폴더> --json       # 기계가 읽는 출력
python3 dream_lint.py <기억 폴더> --strict     # 경고도 실패(종료 코드 2)로
# 옵션: --max-index-lines 200  --max-line-len 150  --dup-threshold 0.6
```
종료 코드: 0 깨끗함 · 1 경고만 · 2 오류(또는 `--strict`의 경고) · 3 폴더가 아님.
cron 예: `0 5 * * * python3 dream_lint.py ~/.claude/projects/<프로젝트>/memory || notify-send "기억 폴더 점검 필요"`

예시 출력(`fixtures/good`):
```
INFO  link-pending     reference-dashboard.md: [[feedback-oncall]]에 해당하는 기억이 아직 없다(쓸 거리로 남겨 둔 것일 수 있다)
기억 파일 4개 · 오류 0 · 경고 0 · 참고 1
exit=0
```

## 5. 테스트 결과
키·모델 없이 도는 `bash test.sh`. CI에서는 e2e가 없다(모델 호출 없음).
```
ok   good: exit 0
ok   good: 미작성 링크는 INFO
ok   good: 파일 4개 집계
ok   bad: exit 2
ok   bad: 없는 파일을 가리키는 색인
ok   bad: 비밀값 패턴
ok   bad: 비밀값 원문은 출력하지 않음
ok   bad: 필수 항목 누락
ok   bad: 프론트매터 없음
ok   bad: 잘못된 type
ok   bad: 색인 형식 위반 줄 번호
ok   bad: 색인에 없는 파일
ok   bad: Why/How 누락 2건
ok   bad: 상대 날짜
ok   bad: 비슷한 설명 쌍
ok   bad: 집계 줄
ok   --json: 파싱되고 counts.error=5
ok   경고만 있으면 exit 1
ok   --strict: 경고도 exit 2
ok   --max-line-len: 짧은 기준이면 긴 줄 경고
ok   없는 폴더는 exit 3
ok   MEMORY.md 없음: ERROR no-index exit 2
ok   색인 줄 수 초과 경고
---
통과 23 · 실패 0
```

나쁜 fixture를 직접 돌린 출력(비밀값은 실행 중에 채운 임시 사본):
```
ERROR index-dangling   MEMORY.md:1: 색인이 없는 파일을 가리킨다: gone.md
ERROR secret           feedback-key.md: 키·토큰·개인키 패턴이 들어 있다. 지우고 회전해야 한다
ERROR missing-field    nodesc.md: 필수 항목이 없다: description
ERROR frontmatter      orphan.md: 프론트매터가 없다(첫 줄이 ---가 아님)
ERROR bad-type         weird-type.md: type은 ['feedback', 'project', 'reference', 'user'] 중 하나여야 한다: note
WARN  index-format     MEMORY.md:7: `- [제목](파일.md) — 한 줄 설명` 형식이 아니다
WARN  not-indexed      nodesc.md: MEMORY.md 색인에 없다. 읽히지 않는 기억이다
WARN  not-indexed      orphan.md: MEMORY.md 색인에 없다. 읽히지 않는 기억이다
WARN  missing-why      project-late.md: project 기억에 **Why:** 줄이 없다
WARN  missing-why      project-late.md: project 기억에 **How to apply:** 줄이 없다
WARN  relative-date    project-late.md: 상대 날짜(다음 주)가 있다. 절대 날짜로 바꿔야 나중에도 읽힌다
WARN  similar          user-a.md: user-b.md와 설명이 86% 겹친다. 하나로 합칠지 본다
기억 파일 7개 · 오류 5 · 경고 7 · 참고 0
exit=2
```
- 이 실행 환경에는 점검할 실제 기억 폴더가 없어, `test.sh`의 "실제 기억 폴더" 검사는 건너뛰었다(있을 때만 도는 검사).

## 6. 한계와 다음 아이디어
- 의미를 모른다. 낡은 사실, 서로 모순되는 기억, 코드와 어긋난 경로는 못 잡는다 → 그건 쿡북처럼 모델이 하는 정리의 몫이다.
- 중복 판정은 단어 겹침이라 표현이 다른 같은 내용은 놓치고, 짧은 설명은 비교하지 않는다(단어 3개 미만).
- 프론트매터 파서는 `name`/`description`/`metadata.type` 용도의 간이 파서다. 여러 줄 값·배열은 읽지 않는다.
- 다음 후보: 본문에 적힌 파일 경로·함수 이름이 지금 저장소에 있는지 확인하는 `--repo` 옵션, `--fix`로 색인 누락 줄 자동 추가, 정리 에이전트 실행 전후의 점검 결과 비교.

## 7. 출처
- claude-cookbooks dreaming 쿡북 커밋: https://github.com/anthropics/claude-cookbooks/commit/d4bd2fb364a7daa77fa90390800ba3aafffd2d1f
- 쿡북 Managed Agents 폴더: https://github.com/anthropics/claude-cookbooks/tree/main/managed_agents
- 이 저장소 news: ../../news/2026-11-05.md
