# Haiku 4.5 시절 코드 (Claude API)
import anthropic

client = anthropic.Anthropic()

resp = client.messages.create(
    model="claude-haiku-4-5-20251001",
    max_tokens=512,
    temperature=0.2,
    top_k=40,
    thinking={"type": "enabled", "budget_tokens": 4000},
    system="You are a classifier.",
    messages=[
        {"role": "user", "content": "Classify: 'refund please'"},
        {"role": "assistant", "content": "{\"label\":"},
    ],
)
print(resp.content[0].text)
