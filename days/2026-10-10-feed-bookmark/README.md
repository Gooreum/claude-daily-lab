# feed-bookmark — 북마크 기반 증분 피드 리더

## 1. 무엇을 만들었나
Atom/RSS 피드를 소스별 북마크로 증분 읽는 단일 파일 CLI(`feed_bookmark.py`, Python 표준 라이브러리만 사용)다. 소스마다 이미 본 entry id를 기억해 두고 새 항목만 Markdown 다이제스트로 내보내며, 읽기에 실패한 소스는 "조용함"이 아니라 "읽기 불가"로 따로 표시하고 종료 코드 2를 돌려준다. 기본 소스는 Claude Code·SDK 릴리스, Cookbook·Skills·Quickstarts·공식 플러그인 커밋, Simon Willison, dev.to, GeekNews, Product Hunt, Latent Space까지 열네 개의 Atom/RSS 피드이고, fixture 기반 단위 테스트(`test.sh`)와 실제 피드 e2e(`e2e.sh`)가 들어 있다.

## 2. 왜 만들었나
2026-10-08 Claude 블로그 글 [Building effective agent automations](https://claude.dev/blog/building-effective-agent-automations/)은 매일 돌아가는 요약 에이전트의 참조 구현을 설명하면서 세 가지를 권한다. 소스별 북마크로 증분 읽기, 읽기 실패를 "조용한 하루"가 아니라 "확인 못 함"으로 보고하기, 읽기 전용 권한. 이 저장소의 매일 06:45 수집 단계(RULES.md 1절)가 정확히 그 모양이라, 조언을 그대로 코드로 옮겨 수집 단계에 끼울 수 있는 도구를 만들기로 했다. 같은 날의 앞선 두 결과물(훅, 모드)과 종류도 겹치지 않는다.

## 3. 어떻게 만들었나
1. **소스 고르기**: Anthropic 뉴스 페이지에는 공식 피드가 없어서, 어떤 저장소든 제공되는 GitHub 릴리스 Atom(`/releases.atom`)을 기본 소스로 삼았다. claude-code, anthropic-sdk-python, anthropic-sdk-typescript, claude-agent-sdk-python 네 개가 모두 200으로 응답하는 것을 먼저 확인했다. 같은 날 저녁 RULES.md 우선 출처를 늘리면서 TypeScript Agent SDK 릴리스, Cookbook·Skills·Quickstarts 커밋 피드(`/commits/main.atom`), Simon Willison의 Claude 태그 피드를 더해 아홉 개가 됐다.
2. **북마크 설계**: 소스당 `{"seen_ids": [...], "last_ok": ISO8601, "last_new_count": N}`. 시각 비교 대신 id 집합을 쓴 이유는 GitHub 피드가 `<updated>`를 릴리스 편집 시마다 바꿔서 시각 기준으로는 같은 항목이 다시 떠오르기 때문이다. id는 Atom `<id>` → RSS `<guid>` → `<link>` → 제목+날짜 해시 순으로 고른다.
3. **첫 실행 처리**: 북마크가 없는 첫 실행은 피드의 과거 항목이 전부 "새 항목"으로 쏟아진다. `--max-age-hours`(기본 48) 안의 항목만 보고하고 나머지는 북마크에만 흡수하게 했다. 북마크가 생긴 뒤에는 나이와 무관하게 "못 본 것"은 전부 보고한다. 북마크가 기준이지 시계가 기준이 아니다.
4. **실패 분류**: fetch 실패(`FetchError`)와 파싱 실패(`ParseError`)를 잡아 그 소스만 `unavailable`로 표시하고 북마크를 건드리지 않는다. 다른 소스는 정상 전진한다. 종료 코드 2로 cron이 실패를 알아채게 했다.
5. **원자적 저장**: 상태 파일은 같은 디렉터리의 임시 파일에 쓰고 `fsync` 후 `os.replace`로 바꿔치기한다. 도중에 죽어도 기존 상태가 남는다.
6. **테스트 가능성**: `urllib`가 `file://`을 그대로 열어 주므로 fixture XML로 네트워크 없이 전 경로를 테스트한다. `--now`로 시각을 고정해 48시간 창 테스트를 재현 가능하게 했다.
7. **막힌 지점**: `seen_ids`를 200개로 자르면 피드가 200개보다 길 때 잘린 항목이 다음 실행에 다시 "새 항목"으로 나온다. 상한을 `max(200, 현재 피드 길이)`로 보정해 해결했고, 그 경계를 테스트로 고정했다.
8. **사용 도구**: Python 3.14, bash, curl. 이 프로젝트도 Claude Code 세션이 만들었다. 계획은 dev-bounce 없이 바로 세웠고, 계획 리뷰용 서브에이전트 스폰은 auto 모드 분류기가 거부해 건너뛰었다.

## 4. 사용법
API 키가 필요 없다. 네트워크가 되면 바로 실행된다.
```bash
cd days/2026-10-10-feed-bookmark
python3 feed_bookmark.py                      # 기본 sources.json, 상태는 ./feed-bookmark-state.json
python3 feed_bookmark.py --dry-run            # 북마크를 저장하지 않고 미리 보기
python3 feed_bookmark.py --json               # JSON 출력
python3 feed_bookmark.py --sources my.json --state ~/.cache/feed-state.json --max-age-hours 24
echo "exit=$?"                                # 0 = 모든 소스 읽음, 2 = 읽기 불가 소스 있음, 1 = 설정/상태 파일 오류
```
`sources.json` 형식. 범용 피드는 `match`(제목 정규식, 대소문자 무시)로 관련 항목만 남긴다:
```json
{ "sources": [
  { "name": "claude-code", "url": "https://github.com/anthropics/claude-code/releases.atom" },
  { "name": "geeknews",    "url": "https://news.hada.io/rss/news", "match": "claude|anthropic|클로드" }
] }
```
매일 수집 루틴에 끼우려면 `python3 feed_bookmark.py >> news/$(date +%F).md` 처럼 출력을 그날 소식 파일에 붙이고, 종료 코드 2를 "확인 못 한 소스 있음"으로 처리하면 된다.

## 5. 테스트 결과
오프라인 테스트 (`bash test.sh`, CI에서도 실행, 2026-10-10):
```
== 1) python3 -m unittest (fixture 기반)
  Ran 20 tests in 0.753s
  OK
  ✅ unittest
== 2) CLI 스모크: 첫 실행 → 두 번째 실행 → 불가 소스 섞기
  ✅ 첫 실행: 48h 내 2개만 new, exit=0
  ✅ 재실행: 조용함, exit=0
  ✅ v2+불가 소스: 추가된 1개만 new, gone은 불가, exit=2
  ✅ 상태 파일: example만 북마크 4개, gone 없음
== 결과: PASS
```
실제 GitHub 피드 e2e (`bash e2e.sh`, 2026-10-10 04:49 KST):
```
== 1) 첫 실행 (sources.json, 48h 창)
   | 새 항목 13개 (소스 4개) · 조용함 0 · 읽기 불가 0
   | ## claude-code — 새 항목 3개
   | - [v2.1.296](https://github.com/anthropics/claude-code/releases/tag/v2.1.296) — 2026-10-09 19:28
   | - [v2.1.295](https://github.com/anthropics/claude-code/releases/tag/v2.1.295) — 2026-10-08 19:48
   | - [v2.1.294](https://github.com/anthropics/claude-code/releases/tag/v2.1.294) — 2026-10-08 05:03
   | ## anthropic-sdk-python — 새 항목 2개
   | ## anthropic-sdk-typescript — 새 항목 7개
   | ## claude-agent-sdk-python — 새 항목 1개
  ✅ exit=0 (모든 소스 읽힘)
  ✅ 북마크 4개 생성
== 2) 재실행
   | 새 항목 0개 (소스 0개) · 조용함 4 · 읽기 불가 0
  ✅ 전부 조용함, exit=0
== 3) 존재하지 않는 소스 추가
   | ## nope — ⚠️ 읽기 불가: HTTP 404 (북마크 유지)
   | > 읽기 불가 소스 1개. 이 결과는 '조용한 하루'가 아니라 '확인 못 한 하루'다.
  ✅ nope만 불가(HTTP 404), exit=2
  ✅ 기존 4개 북마크의 seen_ids 불변, nope 북마크 없음
== 결과: pass=5 fail=0
```
첫 실행이 48시간 창 안의 13개를 정확히 잡았고(앞선 두 프로젝트의 계기였던 2.1.294·2.1.295와 오늘 나온 2.1.296 포함), 재실행은 조용함, 404 소스는 다른 소스의 북마크에 영향을 주지 않았다.

## 6. 한계와 다음 아이디어
- Atom과 RSS 2.0만 해석한다. JSON Feed, HTML 페이지 스크래핑은 지원하지 않는다. Anthropic 뉴스 페이지처럼 피드가 없는 소스는 못 읽는다.
- 항목의 본문(content)은 버리고 제목·링크·날짜만 남긴다. 요약이 필요하면 링크를 따라가야 한다.
- 북마크가 있는 상태에서 피드가 갑자기 오래된 항목을 노출하면(소스 변경 등) 그것도 "새 항목"으로 나온다. 의도된 동작이지만 소음이 될 수 있다.
- 소스를 순차로 읽는다. 소스가 수십 개면 `concurrent.futures`로 병렬화할 만하다.
- 다음: Anthropic 뉴스·Claude 블로그용 HTML 어댑터, 새 항목 본문을 Haiku 5.5로 2~3문장 요약해 `news/YYYY-MM-DD.md` 형식에 맞춰 내보내기, 이 저장소의 예약 작업 1단계(수집)에 실제로 연결하기.

## 7. 출처
- Building effective agent automations (2026-10-08): https://claude.dev/blog/building-effective-agent-automations/
- GitHub Atom 피드: https://github.com/anthropics/claude-code/releases.atom 외 sources.json의 열네 개 (릴리스는 `/releases.atom`, 커밋은 `/commits/main.atom`; dev.to·GeekNews·Product Hunt·Latent Space는 RSS)
- Python `urllib.request`(file:// 지원), `xml.etree.ElementTree`, `email.utils.parsedate_to_datetime` 표준 문서
- 오늘 수집한 소식: ../../news/2026-10-10.md
