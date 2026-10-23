# skill-lint

> `days/2026-10-23-skill-lint/` — Agent Skills(`SKILL.md`) 규격·이식성·위험 패턴 점검 린터.

## 1. 무엇을 만들었나

CLI 스크립트(`skill_lint.py`, 표준 라이브러리만, 키·네트워크·모델 불필요). 폴더를 주면 안의 `SKILL.md`를 전부 찾아 31개 규칙(`--list-rules`)으로 점검하고 `error`(규격 위반·로드 실패·실행하면 위험 확정) / `warn`(동작이 어긋남·사람이 봐야 함) / `info`(이식성 제안)로 줄 번호와 함께 보여 준다. 보는 것은 네 가지다.
- **규격**: `name`(64자·소문자/숫자/하이픈·폴더 이름과 일치), `description`(1024자), `compatibility`(500자), `metadata`(문자열 맵), 본문 500줄, 참조 파일이 실제로 있는지.
- **Claude Code에서 조용히 틀어지는 것**: 따옴표 없는 `description` 안의 `: `(YAML 오류 → 필드 전부 무시), ` #` 뒤 잘림, 오타 난 키(`allowed_tools`), `description`+`when_to_use` 1536자 절단, 불리언이 아닌 값, 넓은 `allowed-tools`(`Bash`, `Bash(python3 *)`), 스킬이 등록하는 `hooks`.
- **이식성**: 규격 밖의 Claude Code 전용 키(`when_to_use`, `model`, `hooks` …)는 claude.ai 업로드·Skills API에서 하드 에러라서 `info`로 알린다.
- **위험 패턴**(`scripts/`와 SKILL.md 코드 블록): `curl … | sh`, 가드 없는 `rm -rf $VAR`, 비밀 경로 읽기와 외부 전송의 조합(유출), `sudo`·`chmod 777`·`eval`, 셸 프로필·SSH 키·크론 변경, 보이지 않는 문자, "사용자에게 알리지 마라" 류 문구, 선언 안 된 네트워크 사용.

## 2. 왜 만들었나

- 소식: [Donating Agent Skills to the Agentic AI Foundation](https://www.anthropic.com/news/donating-agent-skills-to-the-agentic-ai-foundation) (2026-10-22). 스킬 표준이 AAIF로 넘어가고, 로드맵에 버전 릴리스·제안 절차·**스킬 작성·설치자용 보안 지침**이 올랐다. 70곳 넘는 플랫폼이 쓰는 표준이라 "한 곳에서만 돌아가는 스킬"과 "남의 스킬을 그냥 설치"가 둘 다 위험해진다.
- 이 저장소에는 모드(`mod-audit`)·서브에이전트(`agent-scope-lint`)·훅(`hook-exit-audit`) 점검은 있어도 **스킬** 점검이 없었다. 지침이 나오기 전에 쓸 수 있는 최소한의 도구를 먼저 만든다.
- 규격 쪽 근거는 [agentskills.io/specification](https://agentskills.io/specification), Claude Code 쪽 근거는 [code.claude.com/docs/en/skills](https://code.claude.com/docs/en/skills)의 frontmatter 표(알 수 없는 키 무시·1536자 절단·YAML 파싱 오류 시 필드 없이 로드·포터블 키 외 업로드 에러).

## 3. 어떻게 만들었나

1. 규격 문서와 Claude Code 문서를 읽고 규칙 표(`RULES`)를 먼저 정했다. 두 문서가 어긋나는 곳(예: `name`은 규격에서 필수, Claude Code에서는 폴더 이름으로 대체)은 규격 위반을 `error`로 두고 메시지에 Claude Code의 동작을 같이 적었다.
2. PyYAML 없이 돌려야 해서 SKILL.md에서 흔한 모양(`key: 값`, 따옴표 문자열, `|`/`>` 블록, `- ` 목록, 한 단계 중첩 맵, 다음 줄로 이어지는 문자열)만 읽는 작은 파서를 썼다. 진짜 YAML 파서가 아니므로 모양을 못 읽으면 `F02`로 알린다.
3. 고정 픽스처 12개 폴더(`fixtures/`)와 임시 폴더에서 만드는 케이스(길이 한계, 보이지 않는 문자, 코드 블록)로 `test.sh`를 먼저 채웠다.
4. **실제 공개 스킬에 돌려 오탐을 잡았다.** `anthropics/skills`(20개)와 `anthropics/claude-plugins-official`(33개)을 받아 돌리고 아래를 고쳤다.
   - `description:` 다음 줄에 따옴표 문자열이 이어지는 형식을 "description 없음"으로 잘못 읽음 → 이어지는 스칼라를 지원.
   - `self.env = env`·`os.environ`·`== *.env*` 같은 비교문이 "비밀 읽기"로 잡힘 → `.env`는 읽기 동사가 있을 때만, 비교문은 제외.
   - `Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/x.py" *)`처럼 **특정 스크립트만** 허용한 규칙이 "넓다"로 잡힘 → 인터프리터 뒤가 와일드카드뿐일 때만.
   - `[[ "$cmd" == *"rm -rf"* ]]` 안의 문자열이 `rm -rf`로 잡힘 → 명령 위치의 `rm`만.
   - 스킬 작성법 문서가 예시로 든 `references/finance.md`가 "파일 없음 error"로 잡힘 → 링크·실행 줄만 error, 산문 언급은 warn, `Example`/`e.g.` 줄은 제외.
   - "ignore previous instructions"를 인용부호로 인용한 방어 문서 → 인용된 문구는 제외. `version:` 같은 흔한 추가 키는 오타 경고 대신 "metadata로 옮기라"는 info.
5. `e2e.sh`는 린터가 "필드 전부 무시"라고 한 스킬이 실제 Claude Code에서 어떻게 보이는지 Haiku 5.5로 확인하도록 썼다(아래 5절: 이 환경에서는 로그인이 없어 건너뜀).

## 4. 사용법

```bash
# 폴더 하나 또는 상위 폴더(안의 SKILL.md를 전부 찾는다)
python3 skill_lint.py ~/.claude/skills
python3 skill_lint.py .claude/skills ./plugins --min-level warn
python3 skill_lint.py some-skill --json            # 기계가 읽는 출력
python3 skill_lint.py skills --ignore K02,X05      # 이식성·네트워크 선언 info 끄기
python3 skill_lint.py skills --no-scripts          # scripts/ 코드 파일은 보지 않음
python3 skill_lint.py --list-rules
```

종료 코드: 0 = error 없음, 1 = error 있음(CI에서 `skill_lint.py skills --min-level error`), 2 = 사용 오류.

출력 예 (`fixtures/risky`):

```
## fixtures/risky/risky-skill  [FAIL]  error 2 · warn 3 · info 1
  ERROR X01 scripts/install.sh:3  내려받은 내용을 바로 실행한다 — 받은 뒤 내용을 보고 실행하거나 해시를 고정
  ERROR X02 scripts/install.sh:4  가드 없는 rm -rf — 변수가 비면 상위 경로·홈이 지워진다 (${VAR:?} 또는 기준 폴더 검사)
  WARN  X08 SKILL.md:8  사용자에게 숨기거나 이전 지시를 무시하라는 문구
  WARN  X06 scripts/install.sh:7  sudo·chmod 777·eval·base64 해독 실행 — 스킬이 권한 상승이나 난독화된 실행을 한다
  WARN  X09 scripts/install.sh:8  셸 프로필·SSH 키·크론·전역 git/Claude 설정을 바꾼다 — 스킬을 지워도 남는다
  INFO  X05 scripts/install.sh:3  네트워크를 쓰는데 frontmatter compatibility에 적혀 있지 않다 (설치 전에 알 수 없음)
```

## 5. 테스트 결과

`bash test.sh` (이 폴더에서, 키·모델 없음):

```
[1] 종료 코드·옵션
  ✓ error가 있으면 exit 1
  ✓ 깨끗한 스킬은 exit 0
  ✓ warn만 있으면 exit 0
  ✓ 없는 경로는 exit 2
  ✓ SKILL.md가 없는 폴더는 exit 2
  ✓ 모르는 규칙 --ignore는 exit 2
  ✓ --min-level warn은 info를 숨김
  ✓ --ignore K02,T02
  ✓ --list-rules가 규칙 30개 이상
  ✓ --json 구조 (skills·counts·findings)
[2] 규격: 이름·frontmatter
  ✓ N02:SKILL.md:2:error
  ✓ N03:SKILL.md:2:error
  ✓ F01:SKILL.md:1:error
  ✓ F01:SKILL.md:1:error
  ✓ N01:SKILL.md:1:error
  ✓ D01:SKILL.md:1:error
  ✓ F04:skill.md:1:error
[3] YAML 함정
  ✓ F02:SKILL.md:3:error
  ✓ F03:SKILL.md:3:warn
  ✓ 따옴표로 감싼 ': '·' #'는 통과
  ✓ | 블록 스칼라 안의 ': '는 통과
  ✓ F02:SKILL.md:3:error
  ✓ F02:SKILL.md:5:error
[4] 길이 제한
  ✓ D02:SKILL.md:3:error
  ✓ description 999자는 D02 아님
  ✓ D03:SKILL.md:3:warn
  ✓ 1024자 이하는 D02 아님
  ✓ C01:SKILL.md:4:error
  ✓ B01:SKILL.md:505:warn
  ✓ 400줄 본문은 B01 아님
[5] 키·타입·권한
  ✓ K01:SKILL.md:4:warn
  ✓ T02:SKILL.md:5:error
  ✓ M01:SKILL.md:7:error
  ✓ K02:SKILL.md:9:info
  ✓ yes는 info(버전 의존)
  ✓ T01:SKILL.md:4:warn
  ✓ T03:SKILL.md:5:warn
  ✓ T01은 Bash·Bash(python3 *) 두 개만 (Bash(git status:*)·Read는 통과)
[6] 참조
  ✓ R01:SKILL.md:6:error
  ✓ R01:SKILL.md:7:error
  ✓ R01:SKILL.md:8:warn
  ✓ R02:references/DETAILS.md:1:info
  ✓ R01은 3개 (링크·실행 줄은 error, 산문 언급은 warn / URL·앵커·존재하는 파일은 통과)
  ✓ R01: 'Example'·'e.g.' 줄의 예시 파일 이름은 통과
[7] 위험 패턴
  ✓ X01:scripts/install.sh:3:error
  ✓ X02:scripts/install.sh:4:error
  ✓ X06:scripts/install.sh:7:warn
  ✓ X09:scripts/install.sh:8:warn
  ✓ X08:SKILL.md:8:warn
  ✓ X05:scripts/install.sh:3:info
  ✓ X02: ${VAR:?} 가드는 통과
  ✓ X02: 고정 폴더 이름은 통과
  ✓ X02: 주석 줄은 안 봄
  ✓ X04:scripts/backup.sh:3:error
  ✓ X03:scripts/check.sh:2:warn
  ✓ --no-scripts는 scripts/ 안 검사 생략
  ✓ X07:SKILL.md:5:error
  ✓ X01:SKILL.md:7:error
  ✓ X05: compatibility에 적었으면 통과
[8] 오탐 방지
  ✓ good 스킬: 검출 0
  ✓ 코드 블록 밖 산문의 curl|shell 언급은 통과
  ✓ X08: 'do not tell the user that' 일반 문장은 통과
[9] 이 저장소의 실제 스킬 (충돌·오탐 점검)
  ✓ ../../.claude/skills를 크래시 없이 처리 (exit 0)

통과 63 · 실패 0
```

**실제 공개 스킬에 돌린 결과** (오탐 수정 후 최종, 2026-10-23 시점 `main`):

| 대상 | 스킬 수 | error | warn | info | 눈에 띈 진짜 지적 |
|---|---|---|---|---|---|
| `anthropics/skills` | 20 | 2 | 1 | 2 | `claude-api`의 description 1068자(규격 1024 초과)·본문 609줄, `template`의 name이 폴더 이름과 다름 |
| `anthropics/claude-plugins-official` | 33 | 5 | 39 | 30 | `hookify/writing-rules`의 name≠폴더, `m5-onboard`가 본문에서 쓰는 `scripts/onboard.py` 등이 폴더에 없음, warn 39 중 27은 본문에서 산문으로 언급한 파일이 없다는 R01(예시 이름일 수 있어 warn), 나머지는 본문 500줄 초과 6·규격 밖 키 2·`sudo` 등 |
| 이 저장소 `.claude/skills` | 2 | 0 | 4 | 6 | `daily-lab`의 `allowed-tools`에 `Bash(bash *)`·`Bash(python3 *)`·`Bash(node *)`·`Bash(curl *)`(의도된 넓은 권한이지만 사실상 임의 실행) |

(위 표의 합계는 `skill_lint.py <경로> | tail -1` 결과이며, 두 외부 저장소는 `git clone --depth 1`로 받은 시점의 내용이다. 외부 저장소의 파일은 이 저장소에 복사하지 않았다.)

`bash e2e.sh` (Haiku 5.5로 "필드 전부 무시" 주장 확인):

```
린터: yaml-colon은 F02, ok-skill은 깨끗
ERR Not logged in · Please run /login
SKIP: claude 로그인 안 됨
```

→ **e2e는 이 환경에서 실행하지 못했다**(`claude` 로그인 없음, 종료 코드 3). CI에서도 미실행. 따라서 "따옴표 없는 `: `가 있으면 Claude Code가 필드를 전부 무시한다"는 부분은 Claude Code 문서의 설명("YAML이 파싱되지 않으면 필드 없이 로드")과 YAML 문법에 근거한 것이고, 실제 Claude Code에서의 관찰은 아니다.

## 6. 한계와 다음 아이디어

- YAML 파서는 SKILL.md에서 흔한 모양만 읽는다. 앵커·복잡한 중첩·멀티 문서는 못 읽고 `F02`가 오탐일 수 있다(진짜 YAML 파서와 한 번 대조해 볼 가치가 있다).
- 위험 패턴은 줄 단위 정규식이다. `sh -c`·변수에 담은 명령·`curl`을 함수로 감싼 경우·인코딩된 페이로드는 놓친다. "이 스킬은 안전하다"를 보장하지 않으며, 설치 전에 사람이 읽어야 할 줄을 추리는 용도다.
- `X03`(비밀 읽기)은 읽기 동사가 있는 줄만 보므로 `source .env` 같은 건 잡지만 `python -c "open('.env')"`는 놓칠 수 있다.
- 규격 변경(AAIF가 예고한 버전 릴리스)에 맞춰 규칙 표를 갱신해야 한다. 지금 규칙은 2026-10-23에 읽은 agentskills.io 명세 기준이다.
- 다음: ① `--fix`(따옴표 감싸기, `version:`을 `metadata:`로 이동), ② 로컬 스킬 중 `description`이 서로 겹치는 쌍 찾기(어제 소식의 "서브에이전트·스킬 난립" 이야기와 이어짐), ③ AAIF의 보안 지침이 나오면 그 항목과 규칙을 대조.

## 7. 출처

- https://www.anthropic.com/news/donating-agent-skills-to-the-agentic-ai-foundation
- https://agentskills.io/specification
- https://code.claude.com/docs/en/skills
- https://claude.com/resources/articles/building-agents-when-to-fold-subagents-into-your-main-agent-loop
- https://github.com/anthropics/skills
- https://github.com/anthropics/claude-plugins-official
