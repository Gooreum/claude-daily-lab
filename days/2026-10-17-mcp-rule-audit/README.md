# mcp-rule-audit

## 1. 무엇을 만들었나
CLI 스크립트(`mcp_rule_audit.py`, 표준 라이브러리만). Claude Code 설정(`settings*.json`·`.claude.json`), `.mcp.json`, 서브에이전트 정의(`.claude/agents/*.md`의 `tools`/`disallowedTools`), 워크플로·쉘의 `--allowedTools`를 훑어 **2.1.299에서 의미가 바뀐 MCP 권한 규칙**을 찾고, 서버 전체 이름에 `__*`를 붙인 고친 형태를 제안한다.
- `MR001` 맨몸 규칙 `mcp__a`가 이름이 겹치는 서버(`a__b`, `a_x`)까지 덮던 규칙 (allow면 error, deny·ask면 warn)
- `MR003`/`MR004` `mcp__a__b`처럼 서버/도구 경계가 둘 이상으로 읽히거나, `__`가 든 서버 이름을 도구 규칙처럼 쓴 규칙
- `MR005` 서버 이름에 `__`가 있음 (하이픈 권장)

## 2. 왜 만들었나
- 계기: dev.to 10-16 [An Allow Rule for MCP Server 'a' Also Matched 'a__b'](https://dev.to/gabrielanhaia/an-allow-rule-for-mcp-server-a-also-matched-ab-how-claude-codes-names-collided-2cm8)와 Claude Code 2.1.299 변경 기록(`mcp__a`는 `a__b` 서버를 더 이상 덮지 않는다).
- 2.1.299 이후에는 안전한 쪽으로 바뀌었지만, **이전 버전에서 쓰던 규칙이 설정에 그대로 남아 있다**. allow는 의도보다 좁아져 프롬프트가 늘고, deny·ask는 의도한 서버에 안 걸렸을 수 있으며, 업그레이드가 늦은 환경(stable 채널은 약 1주 지연)에서는 여전히 넓게 열려 있다. 규칙 문자열을 눈으로 대조하긴 어려워 기계적으로 찾게 했다.

## 3. 어떻게 만들었나
1. 글의 설명(이름이 평탄한 문자열 `mcp__<서버>__<도구>`, 서버·도구 모두 `__` 허용)을 규칙 세 가지로 옮겼다: 맨몸 규칙의 접두 겹침, `__`가 든 규칙의 여러 해석, 서버 이름의 `__`.
2. 서버 이름은 두 곳에서 모은다. 스캔 대상의 `mcpServers` 키(정규화: 글자·숫자·`_`·`-` 밖의 문자는 `_`)와 `--server`로 직접 넘긴 이름. 플러그인 번들 서버처럼 파일에 안 보이는 서버는 `--server`로 보탠다.
3. 설계 결정: 겹치는 서버가 **실제로 있을 때만** 지적한다. 맨몸 규칙이라는 이유만으로 경고하면 노이즈가 많아, 그건 `-v`의 `MR002`(info)로 뺐다. 옛 파서가 첫 `__`에서 잘랐다는 건 글쓴이의 추정이라(변경 기록에 옛 동작이 없다) 메시지도 "이전 버전에서 ~까지 덮던"으로만 쓰고 단정하지 않았다.
4. 막힌 곳: 직접 지정한 임의 이름 파일(`/tmp/x.json`)이 분류에서 빠졌다. 폴더 스캔은 파일 이름 규칙으로, 직접 지정한 파일은 확장자만 보게 나눠 해결했다. 테스트 쪽에선 `set -u` 때문에 선택 인자 `$3`이 터져 `${3:-}`로 고쳤다.
5. 도구: Python 3.12, `bash test.sh`. 모델 호출이 없어 `e2e.sh`는 없다.

## 4. 사용법
```bash
python3 mcp_rule_audit.py                       # 현재 폴더 (.claude/, .mcp.json, .github/workflows/ 등)
python3 mcp_rule_audit.py ~/.claude ~/.claude.json .   # 사용자 설정까지
python3 mcp_rule_audit.py --server github__enterprise settings.json   # 파일에 없는 서버 이름 보태기
python3 mcp_rule_audit.py --strict --json .     # warn도 실패, JSON 출력 (CI용)
```
종료 코드: 0=error 없음, 1=error(`--strict`면 warn도), 2=경로 오류·읽을 파일 없음. 고칠 때는 출력의 `→` 줄을 따른다. 예: `mcp__github` → `mcp__github__*`.

예시 출력(`fixtures/bad`):
```
fixtures/bad/.claude/agents/reviewer.md:4: error MR001 allow 규칙 `mcp__github`는 2.1.299 이전 버전에서 서버 github__enterprise까지 허용 대상으로 삼았다 (2.1.299부터는 `github` 서버만)
    → mcp__github__*
fixtures/bad/.claude/settings.json:4: error MR001 allow 규칙 `mcp__github`는 2.1.299 이전 버전에서 서버 github__enterprise까지 허용 대상으로 삼았다 (2.1.299부터는 `github` 서버만)
    → mcp__github__*
fixtures/bad/.claude/settings.json:5: error MR001 allow 규칙 `mcp__db`는 2.1.299 이전 버전에서 서버 db_admin까지 허용 대상으로 삼았다 (2.1.299부터는 `db` 서버만)
    → mcp__db__*
fixtures/bad/.github/workflows/claude.yml:9: error MR001 allow 규칙 `mcp__db`는 2.1.299 이전 버전에서 서버 db_admin까지 허용 대상으로 삼았다 (2.1.299부터는 `db` 서버만)
    → mcp__db__*
fixtures/bad/.claude/settings.json:6: warn MR004 `mcp__a__b__whoami`는 서버 a 또는 a__b로 읽힐 수 있다
    → mcp__a__* / mcp__a__b__*
fixtures/bad/.claude/settings.json:10: warn MR004 `mcp__a__b`는 서버 a 또는 a__b로 읽힐 수 있다
    → mcp__a__* / mcp__a__b__*
fixtures/bad/.claude/settings.json:14: warn MR001 ask 규칙 `mcp__github`는 2.1.299 이전 버전에서 서버 github__enterprise까지 확인 요구 대상으로 삼았다 (2.1.299부터는 `github` 서버만)
    → mcp__github__*
fixtures/bad/.mcp.json:4: warn MR005 서버 이름 `github__enterprise`에 `__`가 있어 `mcp__<서버>__<도구>` 경계가 모호하다
    → 이름을 `github-enterprise`처럼 하이픈으로
fixtures/bad/.mcp.json:8: warn MR005 서버 이름 `a__b`에 `__`가 있어 `mcp__<서버>__<도구>` 경계가 모호하다
    → 이름을 `a-b`처럼 하이픈으로
파일 4개 · MCP 규칙 8개 · 서버 6개 — error 4 · warn 5
```

## 5. 테스트 결과
`bash test.sh` (키·모델 없이 돈다. 이 날은 로컬 러너에서 실행):
```
ok   bad 픽스처는 exit 1
ok   MR001: settings allow mcp__github (github__enterprise와 겹침) error
ok   MR001: allow는 error 등급
ok   MR001: ask 규칙은 warn 등급
ok   MR001: 서브에이전트 tools의 mcp__github도 잡힘
ok   MR001: 워크플로 --allowedTools의 mcp__db도 잡힘
ok   MR001: db_admin 도구 deny(mcp__db_admin__drop_table)는 지적 없음
ok   MR004: mcp__a__b가 서버 a / a__b 둘로 읽힘
ok   MR004: mcp__a__b__whoami도 모호
ok   MR005: 서버 이름 github__enterprise, a__b 두 건
ok   줄 번호가 규칙 줄을 가리킴 (settings.json:5 MR001 mcp__db)
ok   Read 같은 비MCP 규칙은 무시
ok   good 픽스처는 exit 0
ok   good 픽스처는 지적 0건
ok   MR003: 서버 x__y 하나뿐일 때 mcp__x__y는 'x의 도구 y'로 읽힘
ok   warn만 있으면 exit 0
ok   --strict면 warn도 exit 1
ok   --server 추가로 파일 하나만 줘도 동작
ok   --server a__b + 규칙 mcp__a → exit 1 (겹침 error)
ok   -v 없이는 info 없음/있으면 MR002는 겹침 없는 맨몸 규칙
ok   없는 경로는 exit 2
ok   읽을 파일이 없으면 exit 2
ok   JSON 파싱 실패는 MR000
ok   norm: 점·공백은 _로 치환
ok   split_list는 괄호 안 쉼표를 보존
ok   와일드카드 규칙 mcp__a__*는 지적 없음
ok   모든 도구 규칙 mcp__는 무시
통과 27 · 실패 0
```
`e2e.sh`는 없다(모델을 부르지 않는 도구). 실제 사용자 설정으로는 돌려 보지 않았고, 모든 검증은 이 폴더의 픽스처 기준이다.

## 6. 한계와 다음 아이디어
- 서버 이름은 스캔한 파일과 `--server`에서만 안다. 플러그인·커넥터·사용자 범위 서버는 `--server`로 보태야 겹침을 잡는다.
- 도구 이름에 `__`가 든 서버의 정확한 경계는 실행 중인 Claude Code에서만 확정된다. 이 도구는 후보를 보여 줄 뿐 어느 쪽인지 단정하지 않는다(`MR004`).
- 워크플로는 `allowedTools`·`claude_args`가 있는 줄의 토큰만 본다. 여러 줄로 나뉜 YAML 블록은 줄별로 키워드가 있어야 잡힌다.
- 다음: `--fix`로 JSON 규칙을 자동 치환, 관리형 설정(`managed-settings.json`) 경로 자동 탐색, `claude mcp list` 출력을 서버 목록으로 받기.

## 7. 출처
- https://dev.to/gabrielanhaia/an-allow-rule-for-mcp-server-a-also-matched-ab-how-claude-codes-names-collided-2cm8
- https://code.claude.com/docs/en/changelog (2.1.299, 2026-10-14의 MCP 허용 규칙 변경)
- https://github.com/anthropics/claude-code/releases/tag/v2.1.302
