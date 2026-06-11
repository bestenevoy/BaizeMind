from pathlib import Path

from config.prompts import CHART_DESCRIPTION_SYSTEM


class ChartParser:
    def __init__(self, ocr_parser=None):
        self._ocr = ocr_parser

    def set_ocr(self, ocr_parser):
        self._ocr = ocr_parser

    def describe_chart(self, image_path: str | Path, output_dir: str = "/tmp/charts") -> str:
        if self._ocr:
            self._ocr.parse(str(image_path), output_dir)
            md = self._ocr.load_markdown(Path(output_dir))
            if md:
                return md
        return self._describe_with_llm(image_path)

    def _describe_with_llm(self, image_path: str | Path) -> str:
        import base64
        from langchain_core.messages import HumanMessage
        from src.llm.deepseek import get_chat_llm
        llm = get_chat_llm(temperature=0.1)
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        msg = HumanMessage(
            content=[
                {"type": "text", "text": CHART_DESCRIPTION_SYSTEM},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ]
        )
        result = llm.invoke([msg])
        return result.content
