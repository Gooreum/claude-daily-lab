# Anthropic과 무관한 다른 LLM 호출: 이 파일의 temperature는 건드리지 않는다
import openai
openai.chat.completions.create(model="gpt", temperature=0.2, top_p=0.9, messages=[])
