import anthropic

client = anthropic.Anthropic()

# 퇴역한 모델 — M01
OLD = "claude-3-5-sonnet-20241022"
LEGACY_ALIAS = "claude-3-7-sonnet-latest"

# 퇴역 예정 — M02 (2026-11-30)
MID = "claude-sonnet-4-5"

# 구형이지만 서비스 중 — M04
NOTE = "claude-opus-4-8"

# 가장 이른 퇴역일이 지난 Haiku — M03
FAST = "claude-haiku-4-5"

# 날짜 고정 ID — M06 (그리고 M03: 가장 이른 퇴역일 2026-11-24)
DATED = "claude-opus-4-5-20251101"

# 표에 없음 — M05
TYPO = "claude-opus-6-1"

# 최신 — 통과
OK = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-1", "claude-haiku-5-5"]

# 같은 줄 허용 표시
PINNED = "claude-3-opus-20240229"  # model-stale: allow 평가 결과 재현용
# model-stale: allow 다음 줄 허용
PINNED2 = "claude-2.1"
