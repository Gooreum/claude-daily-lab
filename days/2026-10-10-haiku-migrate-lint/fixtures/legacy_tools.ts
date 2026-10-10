// Haiku 4.5 computer use (Claude API)
import Anthropic from "@anthropic-ai/sdk";
const client = new Anthropic();

const r = await client.beta.messages.create({
  model: "claude-haiku-4-5",
  max_tokens: 4096,
  betas: ["computer-use-2025-01-24", "fine-grained-tool-streaming-2025-05-14"],
  tools: [
    { type: "computer_20250124", name: "computer", display_width_px: 1024, display_height_px: 768 },
    { type: "text_editor_20250124", name: "str_replace_editor" },
  ],
  messages: [{ role: "user", content: "Open the settings page" }],
});
if (r.stop_reason === "refusal") throw new Error("refused");
