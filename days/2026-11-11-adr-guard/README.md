# adr-guard

## 1. 무엇을 만들었나
Claude Code **UserPromptSubmit 훅** 스크립트 `adr_guard.py`(표준 라이브러리만). 프롬프트를 보내는 순간 저장소의 ADR(설계 결정 기록, 기본 `docs/adr` 등) 중 **채택하지 않은 결정**(`not_adopted`·`rejected`·`declined`·`기각` 등)과 프롬프트의 단어가 2개 이상 겹치면, 제목·상태·기록된 사유·경로를 사실 문장으로 컨텍스트에 붙인다. 겹침이 없으면 아무것도 출력하지 않는다. 보조 명령: `--dry-run "문장"`(훅 없이 결과만 보기), `--lint`(상태·사유가 빠진 ADR 찾기), `--print-rule`(상시 규칙 한 문장), `--print-settings`(settings.json 조각).

## 2. 왜 만들었나
dev.to 11-10 [One Sentence Took My Coding Agent from 0/3 to 3/3 on Rejected Decisions](https://dev.to/kompiro/one-sentence-took-my-coding-agent-from-03-to-33-on-rejected-decisions-2179) — 저자가 자기 저장소(ADR 263개)로 백여 번 돌린 실험에서, 기각한 결정을 ADR에 남겨도 상시 규칙에 "설계 전에 과거 결정을 확인하라"는 한 문장이 없으면 에이전트가 기각된 제안을 다시 내놓았고, 그 문장을 넣자 0/3이 3/3이 됐다. 규칙 한 줄은 에이전트가 따르기를 기대할 수밖에 없으니, 이 훅은 해당할 때만 근거(기각 사유)를 컨텍스트에 직접 붙이는 보강을 만든다. (`news/2026-11-11.md` 3번. 수치는 저자 한 명의 저장소 결과다.) 이 저장소에는 시작 시점 컨텍스트를 넘기는 훅(`red-start`, 11-09)은 있었지만 프롬프트 시점 훅은 없었다.

## 3. 어떻게 만들었나
1. 글에서 두 가지를 가져왔다: 기각한 결정은 **한 줄 사유와 상태만 있어도 충분**하다는 점, 그리고 **읽히려면 확인을 요구하는 문장이 필요**하다는 점. 앞의 것은 `--lint`(사유 없는 기각 찾기)로, 뒤의 것은 훅 출력과 `--print-rule`로 나눴다.
2. ADR 형식은 제각각이라 세 가지를 한 번에 읽는다: front-matter(`status:`·`title:`·`keywords:`·`reason:`), 본문 `Status: …` 줄, `## Status` 절. 사유는 `Reason:`·`Why:`·`이유:` 줄이나 `## Why`·`## Decision`·`## 이유` 절의 첫 줄에서 뽑는다.
3. 겹침은 임베딩이 아니라 단어 집합으로 판단한다. 영문 3자 이상·한글 2자 이상 단어를 뽑고, 한글은 흔한 조사를 떼고, 영문 복수형은 단수와 같게 센다(`diagrams`=`diagram`, 단 `redis`·`class`는 그대로). 불용어는 뺀다. 제목·`keywords`와 **서로 다른 단어 2개 이상** 겹쳐야 붙인다(설정 `min_shared`). `keywords:`가 3개 이하이고 그중 하나가 겹치면 1개로도 붙인다(예: `keywords: bazel`).
4. 출력은 최대 3개 ADR, 사유 240자, 전체 3000자로 자른다(훅 출력 1만 자 한계보다 한참 아래). 문구는 사실만 쓰고 마지막 줄에 "겹치는지 확인하지 않았다"고 적는다. 명령조를 쓰지 않는 이유는 `red-start`와 같다(주입 방어에 걸릴 수 있다).
5. 훅 모드는 모든 경로에서 `exit 0`. 맨 바깥에서 `BaseException`까지 삼키고, 깨진 JSON·숫자 `prompt`·깨진 ADR(빈 파일·바이너리)도 통과시킨다(`hook-manners` 규칙 1).
6. 막힌 점: 처음 구현은 영문 복수형을 단수와 복수 둘 다 집합에 넣어 `diagram`+`diagrams`가 겹침 2개로 세어졌고, `redis`가 `redi`로 잘렸다. 한 단어만 겹치는 프롬프트에도 ADR이 붙는 오탐이어서 단수로 합치고 `-is/-ss/-us` 끝은 건드리지 않게 고쳤다. 테스트 하나는 "훅이 쓴 문구에 명령조가 없는지"를 보는데 ADR 사유 원문에 "do not fit"이 있어 걸렸으므로, 훅이 덧붙인 첫 줄·끝 줄만 검사하도록 바꿨다.
7. 만든 방식: Claude Code로 직접 작성·실행. 모델 호출은 없다.

## 4. 사용법
```bash
# 1) 훅 파일을 프로젝트에 둔다
mkdir -p .claude/hooks && cp adr_guard.py .claude/hooks/
# 2) settings.json에 넣을 조각을 출력해 합친다
python3 adr_guard.py --print-settings
# 3) CLAUDE.md에 상시 규칙 한 문장을 넣는다 (글의 핵심)
python3 adr_guard.py --print-rule
# 4) ADR 상태·사유가 빠진 곳을 점검
python3 adr_guard.py --lint
# 5) 실제로 무엇이 붙는지 훅 없이 보기
python3 adr_guard.py --dry-run "Let's switch the diagram syntax to a YAML style"
# (선택) 폴더가 비표준이면 .claude/adr-guard.json: {"dirs": ["decisions"], "min_shared": 2}
#  또는 환경 변수 ADR_GUARD_DIR=decisions
```
예시 입출력(`examples/`의 가짜 ADR):
```
$ CLAUDE_PROJECT_DIR=examples python3 adr_guard.py --dry-run "Let's drop the brace syntax and switch to a YAML style for diagrams"
Rejected design decisions recorded in this repository that share words with this prompt:
- Move the diagram syntax to a YAML style (status: not adopted, docs/adr/0012-yaml-syntax.md) — recorded reason: edge declarations do not fit a YAML structure, and a half-YAML syntax would only breed confusion. [shared words: diagram, style, syntax, yaml]
Whether this prompt reopens any of them has not been checked.
```
`--json`을 주면 `hookSpecificOutput.additionalContext` 형태로 낸다. API 키는 필요 없다.

## 5. 테스트 결과
`bash test.sh` (키·모델·네트워크 없이 1~2초):
```
ok   - 겹침: YAML ADR(not_adopted)를 찾는다
ok   - 겹침: 기록된 사유를 그대로 보여 준다
ok   - 겹침: exit 0
ok   - 본문 Status: Rejected + ## Why 사유를 읽는다
ok   - 한글: 조사를 떼고 기각 ADR을 찾는다
ok   - 채택(accepted) ADR은 출력하지 않는다
ok   - 겹치는 기각 없음 → 출력 비어 있음
ok   - 무관한 프롬프트: 출력 없음
ok   - 단어 하나만 겹치면 출력 없음
ok   - 복수형 중복 집계 없음(diagrams는 한 단어)
ok   - 사유 없는 기각: 'no reason recorded'라고 적는다
ok   - 사실만: 훅이 쓴 문구에 must/should/please/never/do not 없음
... (위는 39개 중 발췌, 전체 출력은 `bash test.sh`로)
ok   - --print-settings: 유효한 JSON, UserPromptSubmit, timeout 있음
ok   - 소스에 네트워크 모듈 import 없음

통과 39 · 실패 0
```
`--lint`를 `examples/`에 돌린 실제 출력: `ADR 5개 · 채택 안 됨 4개 · 상태 없음 0개 · 사유 없는 기각 1개` + `사유 없음: docs/adr/0020-no-reason.md`.

**e2e 미실행**: 실제 `claude` 세션에서 `UserPromptSubmit` 훅 출력이 컨텍스트로 보이는지, Claude가 그것을 읽고 기각된 제안을 피하는지는 이 환경에서 확인하지 못했다(모델 호출은 시도하지 않았다). 훅 쪽 입출력(stdout 텍스트·`--json` 형태)만 검증했다. 글의 0/3→3/3도 이 훅으로 재현한 것이 아니다.

## 6. 한계와 다음 아이디어
- 실제 Claude Code 세션에서의 확인이 없다. 설정 조각의 구조와 `timeout`은 훅 문서를 따랐을 뿐 이 환경에서 로드해 본 것이 아니다.
- 겹침 판단이 단어 집합이라 의미는 모른다. 동의어("캐시"·"cache")는 못 잇고, 제목에 흔한 단어(예: 제품 이름이 `diagram`인 저장소의 `diagram`)가 많으면 오탐하며, 프롬프트가 ADR 제목과 다른 표현이면 놓친다. 한국어 조사 처리도 흔한 것만 뗀다. 오탐은 `min_shared`·`keywords:`로 조절한다.
- 상태 값은 고정 목록(`not_adopted`·`rejected`·`declined`·`기각`…)으로만 판단한다. `Superseded`·`Deprecated`는 기각으로 보지 않는다.
- ADR 본문이 신뢰할 수 없는 입력(외부 PR로 추가된 ADR)이면 사유 문장이 컨텍스트에 들어가므로 프롬프트 주입 경로가 된다. 신뢰하는 저장소에서만 쓴다.
- 다음: ADR 본문 전체 대신 `index` 파일만 읽어 큰 저장소에서 빠르게 하기. 프롬프트가 아니라 변경된 파일 경로로도 겹침 찾기(`PreToolUse`). `--lint`를 CI에 넣어 사유 없는 기각을 막기.

## 7. 출처
- https://dev.to/kompiro/one-sentence-took-my-coding-agent-from-03-to-33-on-rejected-decisions-2179
- https://dev.to/kompiro/record-what-you-rejected-and-make-your-agent-check-it-lessons-from-495-adrs-499n
- https://code.claude.com/docs/en/hooks
- `news/2026-11-11.md` (이 저장소)
