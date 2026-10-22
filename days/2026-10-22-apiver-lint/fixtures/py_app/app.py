import anthropic
from anthropic.types import MessageParam

client = anthropic.Anthropic(api_key="x", auth_token="y")


def ask(text):
    seed = MessageParam(role="user", content=text)
    return client.messages.create(
        model="claude-sonnet-5-5",
        max_tokens=1024,
        temperature=0.2,
        top_p=0.9,
        messages=[
            seed,
            {"role": "assistant", "content": [
                {"type": "document", "source": {"type": "text", "media_type": "text/plain", "data": "x"}},
            ]},
            {"role": "user", "content": [
                {"type": "text", "text": "cite", "citations": [{"type": "char_location", "cited_text": "x"}]},
            ]},
        ],
    )


def models():
    return client.models.list(betas=["x"])


raw_headers = {"anthropic-version": "2023-06-01", "content-type": "application/json"}
