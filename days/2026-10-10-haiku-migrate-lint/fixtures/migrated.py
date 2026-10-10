# 이미 Haiku 5.5로 옮긴 코드. 린터가 아무것도 잡지 않아야 한다.
import anthropic

client = anthropic.Anthropic()
resp = client.messages.create(
    model="claude-haiku-5-5",
    max_tokens=4096,
    thinking={"type": "adaptive"},
    output_config={"effort": "low"},
    messages=[{"role": "user", "content": "Classify: 'refund please'"}],
)
if resp.stop_reason == "refusal":
    raise SystemExit("declined")
text = next(b.text for b in resp.content if b.type == "text")
print(text)
