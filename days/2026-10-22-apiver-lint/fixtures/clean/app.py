import anthropic

client = anthropic.Anthropic()
msg = client.messages.create(
    model="claude-sonnet-5-5",
    max_tokens=1024,
    messages=[{"role": "user", "content": "hello"}],
)
# 같은 이름의 다른 변수는 오탐이면 안 된다
temperature_label = "warm"
print(msg.content, temperature_label)
