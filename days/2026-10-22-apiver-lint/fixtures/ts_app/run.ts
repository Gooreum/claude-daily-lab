import Anthropic from "@anthropic-ai/sdk";
const client = new Anthropic();

const runner = client.beta.messages.toolRunner({
  model: "claude-opus-5-5",
  max_tokens: 2048,
  compactionControl: { enabled: true, contextTokenThreshold: 100_000 },
  messages: [{ role: "user", content: "hi" }],
});

const old = await client.completions.create({ model: "claude-2.1", max_tokens_to_sample: 10, prompt: HUMAN_PROMPT + "hi" + AI_PROMPT });
const r = await client.messages.create({ model: "claude-opus-5-5", max_tokens: 10, top_k: 5, messages: [] });
