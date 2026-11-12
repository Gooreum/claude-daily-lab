# cc-advisory

## 1. 무엇을 만들었나
설치된 Claude Code 버전(`claude --version`)을 **보안 공지의 수정 버전 표**와 대조하는 CLI이자 **SessionStart 훅** `cc_advisory.py`(표준 라이브러리만). 수정 버전 미만이면 해당 공지(GHSA·CVE·심각도·수정 버전)를 사실 문장으로 알리고 exit 1, 모두 이상이면 한 줄로 통과, 버전을 못 읽으면 exit 2. 훅 모드(`--hook`)는 미달일 때만 `additionalContext`를 내고 어떤 경우에도 exit 0이다. 표는 파일 안에 두 건이 들어 있고, `--table`로 내 공지를 더하거나 통째로 바꾼다.

## 2. 왜 만들었나
dev.to 11-12 [Claude Code below 2.1.251 let code in its Bash sandbox redirect an Edit outside the workspace on macOS (CVE-2026-88968)](https://dev.to/rulestack/claude-code-below-21251-let-code-in-its-bash-sandbox-redirect-an-edit-outside-the-workspace-on-2gp4) — 검사 시점과 사용 시점이 어긋나는 같은 종류의 Edit 경로 결함이 3주 간격으로 두 번(10-05, 10-26) 공지됐다. 글의 수정 버전은 원 공지 두 개(GHSA-5j29-h97v-84ch → 2.1.129, GHSA-5xjx-9qx6-jcrv → 2.1.251)를 직접 열어 일치함을 확인했다. 이 저장소에는 샌드박스 설정(`sandbox-lint`)·모드(`mod-audit`)·디렉터리 신뢰(`dir-trust`) 점검은 있었지만 "버전 자체가 수정 버전 이상인가"를 보는 도구는 없었다. (`news/2026-11-12.md` 2번)

## 3. 어떻게 만들었나
1. 공지 두 개의 GitHub 페이지를 `curl`로 받아 Affected(`< 수정 버전`)·Patched·CVE·게시일을 뽑아 표를 만들었다. 글이 인용한 CVE 번호가 공지 페이지와 같았다.
2. 버전 비교는 문자열이 아니라 `(주, 부, 패치)` 숫자 튜플로 한다(`2.1.99 < 2.1.129`). `2.1.322 (Claude Code)` 같은 출력에서 첫 `X.Y.Z`만 읽는다.
3. 훅은 `hook-manners`(11-02)의 규칙을 따른다: 항상 exit 0, 맨 바깥에서 `BaseException`까지 삼킴, 버전을 모르면(claude 없음·파싱 실패) 조용히 끝, 출력은 평문 사실 문장(명령조 없음, `red-start`(11-09)와 같은 이유).
4. CLI 모드는 반대로 **시끄럽다**: 미달 exit 1, 버전 모름 exit 2. 같은 로직을 쓰되 "알림용(훅)"과 "게이트용(CLI, CI에서 쓸 수 있음)"의 종료 코드를 나눴다.
5. 표 파일(`--table`)은 목록이거나 `{"extend": true|false, "advisories": [...]}`. `fixed`를 못 읽는 항목은 표 전체를 거절한다(조용히 무시하면 점검이 비어 보이기 때문).
6. 막힌 점: 처음 테스트에서 훅의 "claude 없음" 경로를 보려고 `PATH`를 비웠더니 `env`가 `python3`까지 못 찾아 실패했다(테스트 문제). `python3` 절대 경로를 쓰도록 고쳤다. 또 사실 문장의 단수·복수 문법("1 advisory list")이 어색해 고정 문장으로 바꿨다.
7. 만든 방식: Claude Code로 직접 작성·실행. 모델 호출 없음.

## 4. 사용법
```bash
python3 cc_advisory.py                        # claude --version을 점검 (미달 exit 1)
python3 cc_advisory.py --version 2.1.100      # 버전 직접 지정
python3 cc_advisory.py --json                 # JSON 결과
python3 cc_advisory.py --list                 # 공지 표 보기
python3 cc_advisory.py --table my.json        # 공지 추가: {"advisories":[{"id":"X","fixed":"2.1.400","title":"..."}]}
# 세션 시작 훅으로 쓰기
mkdir -p .claude/hooks && cp cc_advisory.py .claude/hooks/
python3 cc_advisory.py --print-settings       # 출력된 조각을 .claude/settings.json에 합친다
```
예시:
```
$ python3 cc_advisory.py --version 2.1.100
Installed Claude Code is 2.1.100. Security advisories with a fixed version above it: 2. Highest fixed version: 2.1.251.
- GHSA-5xjx-9qx6-jcrv (CVE-2026-88968, High) fixed in 2.1.251: TOCTOU race in the Edit tool allows file writes outside the workspace
- GHSA-5j29-h97v-84ch (CVE-2026-103435, High) fixed in 2.1.129: Write-time symlink following (TOCTOU) lets an edit land outside the project
확인한 공지 2개 중 2개가 이 버전에 해당한다.
$ python3 cc_advisory.py --version 2.1.322
Claude Code 2.1.322: 표의 공지 2개 모두 수정 버전 이상이다.
```
키·모델·네트워크가 필요 없다.

## 5. 테스트 결과
`bash test.sh` (키·모델·네트워크 없이 1초 안팎):
```
ok   - 버전 2.1.128 → exit 1, 공지 2개
ok   - 버전 2.1.129 → exit 1, 공지 1개
ok   - 버전 2.1.250 → exit 1, 공지 1개
ok   - 버전 2.1.251 → exit 0, 공지 0개
ok   - 버전 2.1.322 (Claude Code) → exit 0, 공지 0개
ok   - 버전 2.0.999 → exit 1, 공지 2개
ok   - 버전 2.2.0 → exit 0, 공지 0개
ok   - 버전 3.0.0 → exit 0, 공지 0개
ok   - 버전 1.99.99 → exit 1, 공지 2개
ok   - 2.1.99는 2.1.129 미만(숫자 비교)
ok   - 수정 버전 높은 순 정렬
ok   - 버전 못 읽으면 exit 2
ok   - 출력에 CVE·수정 버전이 있다
ok   - 사실만: must/should/please/you 없음
ok   - 통과 문구
ok   - --list: 공지 2줄
ok   - --table: 기본 표에 더해진다(3개 중 1개 해당)
ok   - --table extend=false: 표 교체
ok   - 깨진 표: exit 2, 스택트레이스 없음
ok   - fixed 없는 공지: exit 2
ok   - 가짜 claude 2.1.200 → 미달 exit 1
ok   - 가짜 claude 2.1.322 → exit 0
ok   - claude가 이상한 출력 → exit 2
ok   - 훅: 미달이면 additionalContext JSON, exit 0
ok   - 훅: 최신이면 조용함, exit 0
ok   - 훅: claude 없음 → 조용히 exit 0
ok   - 훅: 깨진 stdin도 exit 0
ok   - 훅: 깨진 표도 조용히 exit 0
ok   - 훅 --plain: 일반 텍스트
ok   - --print-settings: 유효한 SessionStart 조각
ok   - 내장 표: 항목 필드 완비
info - 이 기기 claude: 2.1.322 (Claude Code) → exit 0
ok   - 실제 claude --version 읽기 성공

통과 32 · 실패 0
```
**e2e 미실행**: 실제 Claude Code 세션이 이 훅의 `additionalContext`를 첫 컨텍스트로 읽는지는 확인하지 않았다(이 실행 환경에서 세션을 새로 열지 않았다). 훅 쪽 입출력(JSON 형태·무음·exit 0)만 검증했고, 설정 조각의 `matcher`·`timeout`은 `red-start`(11-09)와 같은 형식을 따랐다. 이 환경의 `claude`는 2.1.322라 실제 점검 결과는 "모두 수정 버전 이상"이었다.

## 6. 한계와 다음 아이디어
- 표는 손으로 넣은 두 건뿐이다. 새 공지를 자동으로 가져오지 않는다. 다음: GitHub `anthropics/claude-code`의 공지 목록(Atom/API)을 읽어 `--table` 파일로 갱신하는 `--sync`(네트워크 필요, 실패 시 기존 표 유지).
- 영향 범위를 "수정 버전 미만"으로만 본다. 공지가 특정 OS(이번 10-26 건은 macOS)만 영향이라고 해도 OS는 보지 않고 버전만 비교한다. 해당 OS가 아니어도 알림이 뜰 수 있다(과잉 알림 쪽으로 틀린다).
- 하한(영향이 시작되는 버전)이 있는 공지는 표현하지 못한다. 두 건 모두 `< 수정 버전`이라 문제가 없었다.
- 훅은 SessionStart 시점의 버전만 본다. 세션 도중 업데이트되는 경우는 다음 세션에야 반영된다.
- 알림은 컨텍스트에 사실로 들어갈 뿐 모델이 따를 보장은 없다. 팀 전체 대응에는 CLI를 기기 점검 스크립트(MDM·CI)에서 exit 코드로 쓰는 편이 확실하다.

## 7. 출처
- https://dev.to/rulestack/claude-code-below-21251-let-code-in-its-bash-sandbox-redirect-an-edit-outside-the-workspace-on-2gp4
- https://github.com/anthropics/claude-code/security/advisories/GHSA-5xjx-9qx6-jcrv
- https://github.com/anthropics/claude-code/security/advisories/GHSA-5j29-h97v-84ch
- https://code.claude.com/docs/en/hooks
- https://code.claude.com/docs/en/sandboxing
- `news/2026-11-12.md` (이 저장소)
