# Bedrock 경로: 구조화 출력은 Haiku 5.5에서 미지원
from anthropic import AnthropicBedrock

client = AnthropicBedrock(aws_region="us-west-2")
resp = client.messages.create(
    model="anthropic.claude-haiku-4-5-20251001-v1:0",
    max_tokens=2048,
    tools=[{"name": "extract", "strict": True, "input_schema": {"type": "object"}}],
    messages=[{"role": "user", "content": "extract fields"}],
)
for block in resp.content:
    if block.type == "text":
        print(block.text)
if resp.stop_reason == "refusal":
    print("declined")
