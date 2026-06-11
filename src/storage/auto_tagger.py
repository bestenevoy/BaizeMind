import json
import re

from src.llm.deepseek import get_chat_llm

TAG_PROMPT = """根据以下文档内容，生成3-5个简洁的中文标签（每个标签2-6个字）。
标签应反映文档的主题、领域、类型等关键信息。

文档内容（前2000字）：
{text}

请直接返回JSON数组格式，例如：["人工智能", "技术报告", "深度学习"]
只返回JSON数组，不要有其他内容。"""


def generate_tags(text: str, max_tags: int = 5) -> list[str]:
    if not text or len(text.strip()) < 20:
        return []

    llm = get_chat_llm(temperature=0.3)
    prompt = TAG_PROMPT.format(text=text[:2000])

    try:
        resp = llm.invoke(prompt)
        content = resp.content.strip()
        match = re.search(r"\[.*?\]", content, re.DOTALL)
        if match:
            tags = json.loads(match.group())
            if isinstance(tags, list):
                return [str(t).strip() for t in tags[:max_tags] if t]
    except Exception:
        pass

    return []
