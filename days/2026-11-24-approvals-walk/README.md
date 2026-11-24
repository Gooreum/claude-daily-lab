# approvals-walk

## 1. 무엇을 만들었나

Claude Approvals의 정책 파일(`.claude/approvals.yml`)을 **서버에 올리기 전에 오프라인에서 걸어 보는 CLI**(Python 표준 라이브러리만, 키·모델·네트워크 없음)다. 변경 파일 목록과 코드 리뷰 결과(`pass`·`fail`·`error`·`incomplete`·`none`)를 주면 파일마다 어떤 규칙이 겹쳐 적용되는지, PR 전체가 몇 명의 승인을 요구하고 Claude가 승인할 수 있는지(아니면 댓글만인지, 막히는지)를 결과별로 한 줄씩 보여 준다. 정책 파일에 모르는 키가 있으면 제품처럼 파일 전체를 거부(exit 2)하고, `--strict`면 빨강·막힘·무심사 파일이 있을 때 exit 1을 내 CI에 걸 수 있다.

## 2. 왜 만들었나

- 계기: 2026-11-23 claude.com의 [Introducing Claude Ship](https://claude.com/resources/articles/introducing-claude-ship) — PR을 리뷰하는 Code Review, CI·충돌에 대응하는 PR Steward, 저장소의 정책 파일로 승인 여부를 정하는 Claude Approvals(베타)가 한 묶음으로 나왔다. 오늘 `news/2026-11-24.md` 1번 항목이다.
- "직접 만들어볼 만하다"고 본 이유: 정책은 기본 브랜치에 병합돼야 효력이 있고(고치려는 PR도 기존 사본으로 판정된다), 서비스는 Team·Enterprise 플랜과 GitHub 저장소가 있어야 쓸 수 있다. 반면 판정 규칙(엄격한 쪽 우선, 첫 참 override, 결과 없음이면 규칙 기본 판정, 규칙 없는 파일은 무심사)은 문서에 글로 정리돼 있어 파일만으로 시뮬레이션할 수 있다. 관찰 모드로 켜기 전에 "이 정책이 내 PR에 무엇을 요구하나"를 미리 보는 도구가 비어 있었다.

## 3. 어떻게 만들었나

1. 먼저 Claude Code에 내장된 `claude-approvals` 스킬 본문을 읽어 판정 규칙과 키 어휘(`version`, `rules`, `paths`, `verdict`, `override`, `if` …)를 확인했다. 키·값을 추측으로 만들지 않기 위해서다.
2. 의존성 없이 돌려야 해서(PyYAML 없음) 정책 파일에 쓰이는 YAML 부분집합(블록 매핑·목록, `{ }`/`[ ]` 흐름 문법, 따옴표, 주석)만 읽는 작은 파서를 직접 썼다. 문서 예시 파일이 그대로 읽힌다.
3. 조건식(`claude/code_review = pass`, `.severity >= high`, `pr/diff_lines <= 50`, `ALL pr/authors = bot:dependabot`, `pr/base = '…'`, `AND`/`OR`)은 **참·거짓·결과 없음 세 값 논리**로 평가했다. 결과가 없으면 "결과가 필요한 첫 override에서 읽기를 멈추고 규칙 기본 판정이 남는다"는 문서의 규칙을 그대로 옮기기 위해서다. `OR`에서 한쪽이 참이면 다른 쪽이 결과 없음이어도 참이다.
4. 규칙 적용은 (a) 경로가 맞고 `if`가 참인 모든 규칙이 적용, (b) 규칙 안에서는 첫 참 override가 필드를 덮어쓰기, (c) 파일마다 가장 엄격한 `claude`(`blocks` > `comments` > `approves`)와 가장 큰 `seats`, (d) PR은 파일 판정의 최댓값, (e) 규칙에 안 맞는 파일은 "무심사", (f) 보호 파일(정책 파일·`.gitattributes` 등)은 사람 한 명 필수에 Claude 승인 불가로 처리했다.
5. **막힌 지점:** 처음 만든 `samples/layered.yml`에서 `services/`·`src/` 규칙이 "덜 요구해도" 승인 수가 2명으로 나와 도구가 틀렸다고 생각했다. 원인은 샘플의 넓은 규칙(`**`, 2명)이 그 경로를 빼지 않아 같이 적용되고 엄격한 쪽이 이기는 것이었다. 도구가 문서대로 옳았고, 이 현상을 `samples/leaky.yml`과 테스트로 남겼다. 샘플은 넓은 규칙에서 해당 경로를 빼 고쳤다. 두 번째로, 리뷰가 `pass`여도 `--severity`가 없으면 `fail OR severity >= high`가 결과 없음이 되어 통과한 PR이 규칙 기본 판정으로 떨어지는 문제가 있어, `pass`일 때만 심각도를 `none`으로 가정하고 출력에 가정을 밝혔다.
6. 사용한 것: Claude Code(`claude-approvals` 스킬 읽기, 코드·테스트 작성), Python 3.12 표준 라이브러리 `unittest`. 모델 호출 없음.

## 4. 사용법

```bash
cd days/2026-11-24-approvals-walk

# 변경 파일 두 개를 리뷰 결과 다섯 가지로 걸어 본다 (기본: --review all)
python3 approvals_walk.py samples/layered.yml --files docs/a.md,src/b.py,services/c.go --diff-lines 40

# 파일별 적용 규칙까지 보기
python3 approvals_walk.py samples/leaky.yml --files docs/a.md --review pass -v

# 목록을 표준입력으로, 봇 PR, 열린 지적의 심각도 지정
git diff --name-only origin/main | python3 approvals_walk.py .claude/approvals.yml --files-from - \
    --author bot:dependabot --review pass --severity high

# CI: 빨강·막힘·무심사 파일이 하나라도 있으면 exit 1 (정책 파일이 깨지면 exit 2)
python3 approvals_walk.py .claude/approvals.yml --files-from files.txt --strict
```

옵션: `--files`(쉼표 구분), `--files-from`(`-`는 표준입력), `--review all|pass|fail|error|incomplete|none`, `--severity none|minimal|low|medium|high|critical`, `--diff-lines`, `--author`(여러 번, `human` 또는 `bot:이름`), `--base`, `--json`, `-v`, `--strict`.

예시 출력(`samples/layered.yml`, docs·src·services 파일 한 개씩):

```
review=pass       → 승인 1명 필요(작성자 제외) · Claude가 승인할 수 있음
review=fail       → 막힘(blocks) — 누가 승인해도 빨갛다: src/b.py, services/c.go
review=none       → 막힘(blocks) — 누가 승인해도 빨갛다: services/c.go
```

API 키가 필요 없어 dry-run 모드는 따로 없다(애초에 전부 오프라인이다).

## 5. 테스트 결과

`bash test.sh`(단위 테스트 25개 + 데모 한 번). CI에서는 e2e가 없다(모델을 부르지 않으므로 해당 없음).

```
test_files_from_stdin (test_walk.Cli.test_files_from_stdin) ... ok
test_json_all_reviews (test_walk.Cli.test_json_all_reviews) ... ok
test_strict_exit_codes (test_walk.Cli.test_strict_exit_codes) ... ok
test_cases (test_walk.Glob.test_cases) ... ok
test_exclusion (test_walk.Glob.test_exclusion) ... ok
test_bad_claude_value (test_walk.Validate.test_bad_claude_value) ... ok
test_unknown_key_refused (test_walk.Validate.test_unknown_key_refused) ... ok
test_version_required (test_walk.Validate.test_version_required) ... ok
test_basic_pass_fail_none (test_walk.Walk.test_basic_pass_fail_none) ... ok
test_blocks_until_pass (test_walk.Walk.test_blocks_until_pass) ... ok
test_bot_author_override (test_walk.Walk.test_bot_author_override) ... ok
test_docs_excluded_from_broad_rule (test_walk.Walk.test_docs_excluded_from_broad_rule) ... ok
test_kleene_or_with_missing_result (test_walk.Walk.test_kleene_or_with_missing_result) ... ok
test_narrow_rule_asking_less_changes_nothing (test_walk.Walk.test_narrow_rule_asking_less_changes_nothing) ... ok
test_observe_decides_nothing (test_walk.Walk.test_observe_decides_nothing) ... ok
test_pass_with_open_high_finding_is_blocked (test_walk.Walk.test_pass_with_open_high_finding_is_blocked) ... ok
test_protected_file_takes_a_person_and_no_claude (test_walk.Walk.test_protected_file_takes_a_person_and_no_claude) ... ok
test_rule_if_without_result_turns_red (test_walk.Walk.test_rule_if_without_result_turns_red) ... ok
test_size_rule_adds_seats_only_when_true (test_walk.Walk.test_size_rule_adds_seats_only_when_true) ... ok
test_strictest_wins_across_files (test_walk.Walk.test_strictest_wins_across_files) ... ok
test_unreviewed_file_and_neutral (test_walk.Walk.test_unreviewed_file_and_neutral) ... ok
test_unsimulated_condition_noted (test_walk.Walk.test_unsimulated_condition_noted) ... ok
test_block_and_flow (test_walk.Yaml.test_block_and_flow) ... ok
test_nested_seats (test_walk.Yaml.test_nested_seats) ... ok
test_sample_loads (test_walk.Yaml.test_sample_loads) ... ok

----------------------------------------------------------------------
Ran 25 tests in 0.193s

OK
--- 데모: 문서 예시 정책 + 파일 두 개
정책: samples/basic.yml [적용(enforce)]   PR: 파일 2개, diff 0줄, 작성자 human
  review=pass       → 승인 2명 필요 · Claude는 댓글만(승인 못 함) · 보호 파일 포함(사람 한 명 필수, 봇은 안 셈)
      src/a.py                           claude=approves seats=1  (규칙1+override1)
      .claude/approvals.yml              claude=comments seats=2  (규칙1+override1, 규칙2)
  ※ review=pass 이고 --severity 가 없어 가장 높은 심각도를 none 으로 가정했다
  ※ 작성자는 승인하지 않아도 자리 하나를 채운다(seats: 1은 작성자 혼자로 충족). 서버 판정의 근사치다.
ALL TESTS PASSED
```

## 6. 한계와 다음 아이디어

- **근사치다.** 서버의 실제 판정이 아니라 스킬 문서의 규칙을 옮긴 것이다. 지원하지 않는 것: `use`·`locals`(재사용 규칙), `nested`(디렉터리별 정책 파일·상속), `reuse`(푸시 뒤 승인 유지), `findings`(지적 해결 권한), `advisory`, `max_age`, `rule/…` 사실, 분류기 `claude/diff`·`repo/…`. 조건에 이런 것이 나오면 "결과 없음"으로 취급하고 출력에 `※`로 알린다. `use`로 verdict를 가져오는 규칙은 건너뛴다.
- 좌석 계산은 단순화했다: 숫자는 그대로, 집합 목록은 `count` 합계, `from`에 `"!pr/authors"`가 있으면 "작성자 제외"만 표시한다. 팀 구성원·실제 승인자·잠김(승인 가능한 사람이 모자라 못 여는 경우)은 계산하지 않는다.
- 보호 파일 목록은 문서가 명시한 것만 넣었고(Anthropic이 바꿀 수 있다고 문서가 경고), `pr/diff_lines`는 사용자가 넣은 숫자를 믿는다. 코드 리뷰 `error`·`incomplete`·`none`은 모두 "결과 없음"으로 같게 처리하되 `= error`·`= incomplete` 비교만 구분한다.
- 다음 아이디어: `git diff --name-only`와 `gh pr view`로 실제 PR의 파일·작성자를 자동으로 채우기, `claude-approvals`가 권하는 "편집 전후 네 가지 PR 걸어 보기"를 정책 파일 두 개의 판정 차이(diff)로 자동화하기, `nested`·`use` 지원.

## 7. 출처

- Introducing Claude Ship (2026-11-23): https://claude.com/resources/articles/introducing-claude-ship
- Claude Code v2.1.331 릴리스 (`/ship` 등이 들어오는 버전대): https://github.com/anthropics/claude-code/releases/tag/v2.1.331
- 판정 규칙의 근거: Claude Code 2.1.331에 내장된 `claude-approvals` 스킬(로컬에서 읽음, URL 없음)
- 오늘 소식 수집: [news/2026-11-24.md](../../news/2026-11-24.md)
