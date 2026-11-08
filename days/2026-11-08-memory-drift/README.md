# memory-drift

> 2026-11-08 · CLI 스크립트(표준 라이브러리만, 모델·키·네트워크 불필요)

## 1. 무엇을 만들었나
Claude의 기억 노트 폴더(`*.md`)를 읽어, 노트 안 `백틱`으로 적힌 **주장**(파일 경로, 함수명(`name()`), 상수·환경 변수, `--옵션`, 커밋 해시)이 대조용 저장소에 아직 있는지 확인하는 `memory_drift.py`다. 없어졌거나 옮겨진 것은 `WARN`으로, 노트가 사건마다 파일 하나씩 불어나는 패턴(날짜 이름 파일이 절반 이상)과 파일 수 상한 초과도 `WARN`으로 알린다. 종료 코드는 0 깨끗함 / 1 경고 있음 / 3 입력 오류다.

## 2. 왜 만들었나
Anthropic 엔지니어링 글 [The components of agent memory](https://www.anthropic.com/research/components-of-agent-memory)(11-06, GeekNews 11-08 소개)는 노트가 처음부터 틀리거나 환경이 바뀌며 낡을 수 있어, 세션 사이에 원본 기록과 대조해 고치는 "드리밍"이 필요하다고 한다. 또 한 모델이 전투·아이템마다 파일을 만들어 413개를 쌓다 길을 잃은 사례를 든다. 이 중 **기계가 대조할 수 있는 부분**(주장이 아직 참인가, 파일이 불어나는가)은 모델 없이 규칙으로 잡히므로 만들어볼 만하다고 봤다. 11-05의 `dream-lint`는 노트 폴더 안쪽 구조(색인·필드·중복)만 보므로 겹치지 않는다. 오늘 news 1번의 첫째·둘째 적용 아이디어에서 골랐다.

## 3. 어떻게 만들었나
1. **주장 추출**: 노트에서 코드 펜스 안과 `drift:ignore`가 적힌 줄을 뺀 뒤, 백틱 토큰만 읽는다. 일반 문장을 건드리면 거짓 경고가 많아지므로 백틱으로 명시한 것만 주장으로 본다.
2. **종류 분류**: 경로(`/`가 있고 확장자가 있거나 `/`로 끝남), `name()`, snake_case·ENV_CASE 이름, `--flag`, 7~40자리 16진 해시. URL·`~`·패턴(`*`, `<`, 공백 등)·저장소 밖 절대 경로는 "건너뜀"으로 세어 거짓 경고를 피한다.
3. **대조**: 경로는 저장소 파일·폴더 목록과, 이름은 저장소 텍스트 전체(1MB 이하 파일, 합계 50MB 상한)에서 단어 경계로 찾는다. 경로가 없는데 같은 파일명이 다른 곳에 있으면 "옮겨졌나?" 힌트를 붙인다. 해시는 `git cat-file`로 확인한다.
4. **심각도 결정**: 외부 도구의 옵션일 수 있는 `--flag`는 `INFO`로 낮췄다. 있는 커밋 해시는 `git log`로 읽히는 정보라 `INFO`(sha-derivable)로 알린다. 글이 말한 "환경에서 읽히는 정보는 노트에 둘 필요가 적다"를 반영했다.
5. **막힌 지점**: 이 저장소의 README들로 실사용 시험을 하자 `.md`처럼 확장자만 적은 토큰이 경로로 오인돼 `WARN`이 났다. 점으로 시작하는 단순 토큰은 건너뛰도록 고치고 테스트에 넣었다.
6. 만든 도구: Claude Code(Edit·Bash), Python 3 표준 라이브러리(`argparse`, `re`, `subprocess`로 git만 호출).

## 4. 사용법
```bash
cd days/2026-11-08-memory-drift
python3 -I memory_drift.py <기억 폴더> --repo <대조할 저장소>      # 예: ~/.claude/projects/<프로젝트>/memory  --repo ~/Code/내프로젝트
python3 -I memory_drift.py <기억 폴더> --repo . --json            # 기계가 읽는 JSON
python3 -I memory_drift.py <기억 폴더> --repo . --max-files 20    # 파일 수 상한 바꾸기 (기본 30)
```
출력 예(고장 샘플):
```
WARN  path-missing   project-old.md:8 — `lib/app.py` 없음 (같은 이름이 src/app.py에 있음 — 옮겨졌나?)
WARN  ident-missing  project-old.md:9 — `retry_with_backoff()` 를 저장소에서 찾지 못함 (이름이 바뀌었거나 지워졌나?)
INFO  flag-missing   project-old.md:12 — `--dry-run` 를 저장소에서 찾지 못함 (외부 도구 옵션이면 무시)
WARN  sha-missing    project-old.md:13 — 커밋 `deadbeefcafe1234` 가 저장소에 없음 (다시 쓴 이력이거나 틀린 해시)
노트 2개(491바이트) · 대조한 주장 7개 · 건너뜀 0개 · 경고 6 · 참고 1
```
- 이 저장소 밖의 사실을 적은 노트(외부 서비스 이름 등)는 그 줄에 `<!-- drift:ignore -->`를 붙이면 건너뛴다.
- 경로는 **대조 저장소의 루트 기준**으로 푼다. 노트가 "README 옆 상대 경로"를 쓰면 거짓 경고가 나온다(6절).
- 모델·키가 필요 없어 `--dry-run`은 따로 없다.

## 5. 테스트 결과
`bash test.sh`(키·모델 없이 로컬 파일만 사용, CI에서 그대로 돈다). e2e는 모델을 쓰지 않아 만들지 않았다.
```
ok   good: exit 0
ok   good: 6개 주장 모두 통과
ok   good: 코드 펜스 안은 검사 안 함
ok   stale: exit 1
ok   stale: 옮겨진 경로에 힌트
ok   stale: 지워진 문서 경로
ok   stale: 지워진 스크립트 경로
ok   stale: 없는 함수 이름
ok   stale: 없는 환경 변수
ok   stale: 없는 옵션은 INFO
ok   stale: 없는 커밋 해시
ok   stale: 줄 번호 표시
ok   stale: 집계
ok   sha: 있는 커밋은 경고 아님
ok   sha: git log로 읽히는 정보라 INFO
ok   ledger: exit 1
ok   ledger: 날짜 이름 6/8 감지
ok   count: 상한 초과 경고
ok   json: 파싱 가능, 경고 0
ok   input: 없는 기억 폴더 → exit 3
ok   input: 없는 저장소 → exit 3
ok   input: 노트 없는 폴더 → exit 3
ok   skip: 외부 참조는 경고 없음
---
통과 23 · 실패 0
```
실사용 시험(이 저장소의 11-03~07 README 5개를 노트처럼 대조, 수정 후):
```
$ python3 -I memory_drift.py /tmp/readme-notes --repo .
WARN  path-missing   2026-11-07-deny-preview.md:31 — `fixtures/settings.json` 없음 (같은 이름이 days/2026-11-07-deny-preview/fixtures/proj/.claude/settings.json에 있음 — 옮겨졌나?)
WARN  path-missing   2026-11-07-deny-preview.md:31 — `fixtures/calls.txt` 없음 (같은 이름이 days/2026-11-07-deny-preview/fixtures/calls.txt에 있음 — 옮겨졌나?)
WARN  event-ledger   (폴더) — 노트 5개 중 5개가 날짜 이름 — 사건마다 파일 하나씩 쌓는 패턴. 주제별로 합치면 읽는 비용이 준다
노트 5개(38370바이트) · 대조한 주장 58개 · 건너뜀 131개 · 경고 3 · 참고 0
```
- 경로 경고 둘은 README가 자기 폴더 기준 상대 경로를 써서 난 것이라 도구의 한계가 드러난 사례다(6절). 힌트가 가리키는 실제 위치는 맞았다.
- 이 세션의 실제 Claude 기억 폴더(`~/.claude/projects/.../memory`)는 비어 있어 거기에는 시험하지 못했다.
- 첫 시도에서 `.md`가 경로로 오인되는 거짓 경고가 있었고, 고친 뒤 위 결과가 됐다.

## 6. 한계와 다음 아이디어
- **존재 여부만 본다.** 경로·이름이 있다는 것까지만 확인하고, 노트의 *내용*(예: "재시도 상한은 3")이 여전히 맞는지는 모른다. 그것은 원본 기록과 대조하는 모델 단계(진짜 드리밍)의 몫이다.
- 경로를 대조 저장소 **루트 기준**으로만 푼다. 노트 파일 기준 상대 경로 모드(`--relative-to-note`)가 후보다.
- 백틱으로 적지 않은 주장은 못 본다. 이름 대조는 단어 경계 일치라 우연히 같은 단어가 다른 곳에 있으면 낡은 노트를 놓친다(거짓 음성).
- `event-ledger`는 파일명이 날짜로 시작하는지만 보는 거친 기준이다. 노트가 날짜 이름을 쓰는 게 정상인 폴더(일지)는 `--no-ledger` 같은 끄는 옵션이 필요하다.
- 다음 아이디어: `dream-lint`와 한 번에 돌리는 묶음 실행, 낡은 주장에 `last-verified` 날짜를 프론트매터로 기록, 세션 JSONL에서 노트 주장과 모순되는 도구 결과 찾기.

## 7. 출처
- Anthropic 엔지니어링 "The components of agent memory"(2026-11-06): https://www.anthropic.com/research/components-of-agent-memory
- GeekNews 소개 "에이전트 메모리 설계"(11-08): https://news.hada.io/topic?id=36775 (확인 시점에 접속 불가: 403, RSS 목록으로는 읽힘)
- 관련 앞선 결과물 dream-lint(11-05)의 계기: https://github.com/anthropics/claude-cookbooks/commit/d4bd2fb364a7daa77fa90390800ba3aafffd2d1f
- 오늘의 news: [news/2026-11-08.md](../../news/2026-11-08.md)
