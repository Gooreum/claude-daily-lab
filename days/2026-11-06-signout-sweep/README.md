# signout-sweep

## 1. 무엇을 만들었나
CLI 스크립트(`signout_sweep.py`, 표준 라이브러리만 사용). 멤버 이메일(또는 `user_…` id) 목록을 받아 Claude Enterprise Admin API의 새 엔드포인트 `POST /v1/organizations/users/{user_id}/sign_out`로 "모든 기기에서 로그아웃"을 일괄 보낸다. 기본은 네트워크를 쓰지 않는 dry-run이고, `--apply`와 `ANTHROPIC_ADMIN_KEY`가 있어야 실제로 보낸다. 주 소유자(400)·없는 멤버(404)·모호한 조회·429·503을 사람별로 구분해 표로 돌려주고, 로그아웃으로 끝나지 않는 것(API 키·클라우드 세션·루틴 등) 체크리스트를 같이 출력한다.

## 2. 왜 만들었나
- 소식: Claude Enterprise 보안·관리 업데이트 (2026-11-05) — https://claude.com/resources/articles/claude-enterprise-security-updates, 사용법 https://platform.claude.com/docs/en/manage-claude/user-management#sign-a-member-out-everywhere
- 이 API는 베타라 헤더(`anthropic-beta: admin-user-sign-out-2026-10-08`)를 직접 붙여야 하고, 이메일로 바로 부를 수 없어 먼저 멤버를 조회해야 한다. 기기 분실·퇴사 같은 급한 때 사람마다 콘솔에서 누르는 대신 목록 하나로 돌리고, "로그아웃했으니 끝"이라는 착각(API 키·루틴은 계속 산다)을 도구가 매번 상기시키게 하면 쓸모가 크다고 봤다. news/2026-11-06.md 1번의 적용 아이디어 첫째·셋째가 그대로 이 도구다.

## 3. 어떻게 만들었나
1. 공식 문서(user-management 페이지)에서 경로·헤더·키 범위(`write:members`, 조회는 `read:members`)·응답 코드 표를 읽고 그대로 옮겼다. 오류 코드는 `error.details.error_code`에 있다.
2. 설계 결정:
   - **dry-run이 기본.** 로그아웃은 되돌릴 수 없는 일이라 `--apply`를 명시해야 보낸다. 키는 인자로 받지 않고 환경변수로만 읽고 출력하지 않는다.
   - **치명 오류(401/403/베타 미등록)는 즉시 중단**하고 남은 대상 수를 알린다. 같은 키로 나머지도 똑같이 실패하기 때문이다. 사람 단위 오류(400 주 소유자, 404, 모호함)는 건너뛰고 계속한다.
   - **429는 `retry-after`(상한 `--wait-cap`)만큼 기다려 재시도, 503은 점증 대기**. 문서가 "재시도해도 안전(멱등)"이라 했고 503은 일부만 끝났을 수 있어서다.
   - **조회 결과가 둘 이상이면 고르지 않는다**(`ambiguous`). 목록 API는 `jane+x@…`를 `jane@…`와 같은 사람으로 맞추므로, 변형으로 맞은 경우는 메모에 남긴다.
   - **`--recheck-after SEC`**: 문서가 "진행 중인 로그인은 5분 뒤까지 끝날 수 있다"고 해서, 로그아웃된 사람에게만 같은 요청을 한 번 더 보내는 옵션(문서 권장 300초).
3. 실제 Admin 키가 없는 환경에서도 시험하려고 `mock_server.py`(모의 Admin API)를 같이 두었다. 헤더·키 검증과 400/401/403/404/429/503 응답을 흉내 내고 받은 요청을 로그로 남긴다.
4. 시험이 정말 잘못을 잡는지 베타 헤더를 일부러 빼 보니 apply 관련 검사가 FAIL로 바뀌었고, 원복 후 모두 통과했다.
5. 이 작업은 Claude Code(Sonnet 5.5)가 했다. 모델 호출 기능은 없다.

## 4. 사용법
```bash
# 1) 계획만 보기 (키·네트워크 불필요)
python3 signout_sweep.py -f fixtures/members.txt
python3 signout_sweep.py jane@corp.example user_01AbCd... --json

# 2) 실제로 보내기 (write:members·read:members 범위의 Admin API 키)
export ANTHROPIC_ADMIN_KEY=...           # 비밀값: 셸 기록·저장소에 남기지 말 것
python3 signout_sweep.py -f members.txt --apply
python3 signout_sweep.py -f members.txt --apply --recheck-after 300   # 5분 뒤 한 번 더
```
- 목록 파일: 한 줄에 하나, `#` 뒤는 주석, `-`이면 표준입력.
- 종료 코드: 0 전원 로그아웃됨 · 1 일부 건너뜀/실패(표 확인) · 2 사용법 오류·치명 오류(키 없음·403·베타 미등록).
- 옵션: `--tries`(재시도 포함 최대 시도, 기본 3), `--wait-cap`(retry-after 최대 대기, 기본 30초), `--base-url`(테스트용).

예시 출력(모의 서버, `--apply`):
```
대상                         user id                        결과           메모
alice@x.test                 user_alice                     signed_out     
bob@x.test                   user_bob                       primary_owner  주 소유자는 로그아웃시킬 수 없다 — 본인이 계정 설정에서 해야 한다
zed@x.test                                                  not_member     이 조직에 그 이메일 멤버 없음
erin@x.test                  user_erin                      failed         503 — 일부만 끝났을 수 있다, 다시 보내면 나머지를 끝낸다
```

## 5. 테스트 결과
`bash test.sh` (키·모델·외부 네트워크 없음, 로컬 모의 서버 사용). e2e.sh는 없다 — 실제 Admin 키로 사람을 로그아웃시키는 검증은 일부러 두지 않았다.
```
ok   dry-run: 잘못된 대상이 있으면 exit 2
ok   dry-run: 네트워크 안 썼다고 밝힘
ok   dry-run: 중복·주석 제거해 대상 5명
ok   dry-run: 베타 헤더를 계획에 표시
ok   dry-run: 안 끝나는 것 체크리스트
ok   dry-run --json: 파싱되고 exit 0
ok   --apply인데 키가 없으면 exit 2
ok   apply: 일부 실패면 exit 1
ok   apply: alice 로그아웃됨
ok   apply: 주 소유자는 건너뜀(400 코드 판별)
ok   apply: 없는 멤버는 not_member
ok   apply: 429는 retry-after 뒤 재시도해 성공
ok   apply: 503은 재시도 후 failed + 재전송 안내
ok   apply: 조회가 둘이면 ambiguous, 고르지 않음
ok   apply: 이메일 변형도 한 명으로 찾고 메모
ok   apply: user id 직접 지정 → 404는 not_member
ok   apply: 요약 줄
ok   apply: 끝나지 않은 것 안내 출력
ok   서버: 모든 로그아웃 요청에 베타 헤더
ok   서버: 조회에는 베타 헤더를 안 보냄
ok   서버: anthropic-version 헤더 전송
ok   서버: dan은 429 뒤 재시도로 2번
ok   서버: erin은 3번 시도 후 포기
ok   서버: 키 값이 출력에 새지 않음
ok   recheck: exit 0
ok   recheck: alice에게 로그아웃 요청 2번
ok   recheck: JSON에 recheck 결과
ok   403: exit 2로 중단
ok   403: write:members 안내와 남은 대상 3명
ok   403: 첫 요청에서 멈춤(나머지 2명은 안 보냄)
ok   베타 미등록: exit 2 + 콘솔 대안 안내
ok   401(조회 단계): exit 2
ok   연결 실패: failed로 기록하고 exit 1

통과 33 · 실패 0
```
CI에서도 같은 명령이 돈다(모델 호출 없음).

## 6. 한계와 다음 아이디어
- **실제 Anthropic 서버에는 한 번도 보내 보지 않았다.** 이 환경에 Enterprise Admin 키가 없다. 모의 서버는 공식 문서의 응답 표를 보고 내가 만든 것이라, 문서와 실제 응답이 다르면 이 테스트로는 못 잡는다(특히 `error.details.error_code` 위치).
- 문서의 "OAuth 토큰은 조직 한정, 세션은 계정 전체" 때문에 다른 조직 멤버 로그아웃까지 번지는 영향은 도구가 막지 못한다. 대상 목록 확인은 사람이 한다.
- 감사 로그(Activity Feed)를 읽어 "5분 뒤 재로그인이 있었는가"를 자동 판단하는 기능은 없다. `--recheck-after`는 무조건 한 번 더 보낼 뿐이다.
- 자기 자신(소유자)에 대한 요청은 문서상 Admin API에서도 막힐 수 있으나 따로 처리하지 않고 `failed`/400 메모로 나온다.
- 다음 아이디어: ① 부모 조직 키(401)와 조직 키를 구분해 안내 ② 다른 조직 키 여러 개로 같은 사람을 순회 ③ SDK 지원 버전(Python 2.6.0·TS 1.6.0, `client.beta.organization.users.sign_out`)이 쓰이면 HTTP 호출을 SDK로 교체.

## 7. 출처
- https://claude.com/resources/articles/claude-enterprise-security-updates
- https://platform.claude.com/docs/en/manage-claude/user-management (Sign a member out everywhere)
- https://platform.claude.com/docs/en/release-notes/overview (2026-11-05)
- https://github.com/anthropics/anthropic-sdk-python/releases/tag/v2.6.0
- https://github.com/anthropics/anthropic-sdk-typescript/releases/tag/sdk-v1.6.0
