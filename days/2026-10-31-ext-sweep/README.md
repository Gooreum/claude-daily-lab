# ext-sweep

## 1. 무엇을 만들었나

CLI 스크립트(`ext_sweep.py`, 표준 라이브러리만). 에디터 확장 공급망 사고 뒤에 "내 PC에 흔적이 남았나"를 읽기 전용으로 훑는다. 세 군데를 본다: ① VS Code·Cursor·Windsurf·VSCodium·vscode-server의 Claude Code 확장 폴더(영향 버전, `package.json`과 폴더 이름의 불일치, 확장 파일 안의 `authorized_keys`·`ssh -R`·LaunchAgents·`schtasks`·포트 문자열), ② `~/.ssh/authorized_keys`(최근 수정, 주석 없는 키, 옵션이 붙은 키, 내가 아는 키 목록에 없는 키), ③ 자동 실행 위치(macOS LaunchAgents, Linux systemd 사용자 유닛·autostart, Windows 시작 프로그램 폴더). 결과는 HIGH/MEDIUM/INFO이고 종료 코드는 0/1·2(HIGH)/64(사용법 오류)다. 아무것도 고치거나 지우거나 실행하지 않는다.

## 2. 왜 만들었나

소식 [Cursor 마켓플레이스의 Claude Code 확장에 SSH 백도어 (GeekNews 10-31)](https://news.hada.io/topic?id=36288) 때문이다. 전한 내용으로는 변조 확장 2.1.312·2.1.313이 자동 업데이트로 퍼져 공격자의 SSH 키를 `authorized_keys`에 넣고 역방향 터널을 만들려 했고, 확장을 지워도 LaunchAgent·예약 작업이 남는다. 이런 사고에서 가장 급한 일은 몇 분 안에 "있었나, 남았나"를 가리는 것인데, 확장 폴더 한 곳만 `ls`하면 절반만 본 것이다. 새 기능이 아니라 새 사건에 대한 도구이고, 가짜 HOME 하나로 키·네트워크 없이 시험할 수 있어 골랐다. 이 사건은 웹 검색으로 독립 확인하지 못했다(`news/2026-10-31.md` 3번). 그래서 기본 지표(버전 2.1.312·2.1.313, 포트 8099)는 보도 기반 "참고용"이고 인자로 바꾼다.

## 3. 어떻게 만들었나

1. 보도에서 지표를 추렸다: 영향 버전, `authorized_keys` 추가, 역방향 터널, macOS LaunchAgent·Windows 예약 작업·시작 프로그램, 8099 포트 전송, 정상 버전 번호를 재사용한 변조본. 확인된 지표는 아니므로 코드 맨 위 상수와 인자(`--bad-version`, `--port`)로 분리했다.
2. **버전만 믿지 않는다.** 정상 버전 번호를 재사용한 변조본이 있다고 해서, 폴더 이름과 `package.json` 버전이 다르면 MEDIUM, `package.json`이 영향 버전이면 HIGH로 본다. 확장 파일 내용도 읽어 정상 확장에 있을 이유가 없는 문자열(`authorized_keys`, `ssh … -R 포트:`)은 HIGH, 자동 실행 등록·지표 포트 문자열은 MEDIUM으로 둔다.
3. **읽기 전용·링크 비추적.** `os.walk(followlinks=False)`로 걷고 심볼릭 링크 파일·폴더는 건너뛴다(10-30 소식 4번 "링크를 따라가 지웠다"의 교훈을 점검 도구에도 적용). 파일은 3MB 이하·확장당 4000개까지만 읽는다.
4. **키는 지문만 출력한다.** `authorized_keys`의 키 본문은 찍지 않고 `SHA256:…` 지문과 주석만 낸다. `--known-keys`에 내가 아는 공개 키 줄이나 지문을 적어 주면 목록에 없는 키를 HIGH로 본다.
5. 대응 순서(네트워크 차단 → 지속성 수동 제거 → 자격 증명 재발급 → 공식 IOC로 재확인)는 HIGH일 때만 출력한다. "확장만 지우면 끝"이라고 말하지 않는 것이 요점이다.
6. `test.sh`는 임시 가짜 HOME에 확장·키·LaunchAgent 등을 만들어 48개를 검증한다. 처음 돌린 결과가 모두 통과라 테스트가 느슨하지 않은지 의심해, 규칙마다 "걸려야 하는 것"과 "걸리면 안 되는 것"(18099 같은 긴 숫자, `.txt`, 다른 확장 ID)을 짝으로 넣었다.
7. 도구: Claude Code(WebFetch·Bash)로 소식을 읽고 작성했다. 모델 호출 기능은 없다.

## 4. 사용법

```bash
cd days/2026-10-31-ext-sweep
python3 ext_sweep.py                       # ~ 를 점검. 신호 없음이면 exit 0
python3 ext_sweep.py -v                    # 설치된 Claude Code 확장 버전·키 개수도 표시
python3 ext_sweep.py --known-keys ~/known_keys.txt   # 내 공개 키 줄/SHA256 지문 목록에 없는 키를 HIGH로
python3 ext_sweep.py --bad-version 2.1.315 --port 9999 --since 30   # 지표를 바꿔 다시 점검
python3 ext_sweep.py --home /path/to/mounted/home --json             # 다른 HOME(마운트한 디스크)을 JSON으로
```

HIGH가 있으면 출력 끝에 대응 순서 4단계가 나온다. 종료 코드: 0 신호 없음, 1 MEDIUM만, 2 HIGH, 64 사용법 오류.

## 5. 테스트 결과

CI 러너에는 `claude` CLI·로그인이 없으므로 e2e는 두지 않았다(CI에서는 e2e 미실행). 모델 호출이 없는 도구라 `test.sh`가 전부다.

```
$ bash test.sh
== 깨끗한 HOME
  ✅ 빈 HOME은 신호 없음, 확장 없음 안내 (exit=0)
  ...
== 영향 버전
  ✅ 2.1.312 폴더는 HIGH ext-bad-version (exit=2)
  ✅ 대소문자가 달라도 잡는다 (exit=2)
== 버전 재사용(폴더 이름과 package.json 불일치)
  ✅ 폴더는 정상인데 package.json이 2.1.313이면 HIGH (exit=2)
== 확장 파일 안의 문자열
  ✅ 확장 폴더 안 심볼릭 링크는 따라가지 않는다 (exit=0)
== authorized_keys
  ✅ --known-keys 목록에 없는 키는 HIGH (exit=2)
== 자동 실행 위치
  ✅ ssh 터널이 든 LaunchAgent는 오래돼도 HIGH (exit=2)
== 출력 형식과 안전성
  ✅ 키 본문(base64)은 출력하지 않고 지문만 보인다
  ✅ 점검 전후로 파일·수정 시각이 그대로다(읽기 전용)

통과 48 · 실패 0
```

실제 HOME(GitHub Actions 러너)에 돌린 결과는 `신호 없음 · 확장 폴더를 찾지 못했다 · exit 0`이고, 없는 HOME은 exit 64다. ⚠ 실제 변조 확장 샘플이나 감염된 PC로는 시험하지 못했다. 테스트의 HIGH 사례는 모두 보도 내용을 바탕으로 직접 만든 가짜 파일이다.

## 6. 한계와 다음 아이디어

- **지표가 미검증이다.** 영향 버전·포트·지속성 방식은 GeekNews 한 건(Cursor 공지 인용)에 의존하고 독립 확인이 없다. 공식 공지의 해시·도메인·파일 이름이 나오면 `--ioc-file`로 읽어 들이는 기능이 필요하다.
- Windows 예약 작업(`C:\Windows\System32\Tasks`, SYSTEM 권한)과 레지스트리 Run 키, macOS 로그인 항목·`launchctl list`, Linux `crontab -l`은 HOME 밖이거나 명령 실행이 필요해 보지 않는다. 시작 프로그램 폴더·LaunchAgents·systemd 사용자 유닛만 본다.
- 확장 파일 내용 검사는 문자열 매칭이라 난독화된 코드를 못 잡고, 정상 확장이 `authorized_keys` 문자열을 가진 경우 오탐이 난다. 이미 변조가 지워졌거나 확장을 삭제한 PC에서는 `authorized_keys`·지속성 쪽 신호만 남는다.
- `authorized_keys`의 MEDIUM("주석 없는 키")은 정상 사용자에게도 흔해 `--known-keys`를 쓰는 편이 정확하다.
- 다음: 8099 같은 포트로 나가는 현재 연결을 `/proc/net`·`lsof`로 보는 `--live`, 공식 IOC 파일 입력, 점검 결과를 해시로 남겨 다음 실행과 비교하는 기준선 기능.

## 7. 출처

- https://news.hada.io/topic?id=36288 — Claude Code 확장 변조로 개발자 시스템에 SSH 백도어 배포 (확인 시점에 curl `HEAD`가 403(봇 차단)이라 접속 불가로 표시. 같은 날 WebFetch로는 읽힘)
- https://github.com/anthropics/claude-code/releases/tag/v2.1.316 — 같은 시기 Claude Code 릴리스
- https://dev.to/ramdai_bista/a-claude-code-sub-agent-followed-614-windows-junctions-out-of-a-test-mirror-deleting-48000-live-2h23 — 링크를 따라가지 않는 설계의 계기
- https://corgea.com/research/glasswasm-open-vsx-solana-wasm-c2 — 다른 OpenVSX 확장 사건(지표 설계 참고, 이번 사건과 무관)
- `news/2026-10-31.md` — 오늘의 수집과 선정 이유
