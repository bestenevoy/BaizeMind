import re
from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter


class HierarchicalChunker:
    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 64):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=[
                "\n\n",
                "\n",
                "。",
                "！",
                "？",
                "；",
                "，",
                "",
            ],
        )

    def chunk(self, doc_id: str, markdown: str) -> list[dict[str, Any]]:
        tree = self._build_heading_tree(markdown)
        chunks = []
        for node in tree:
            chunks.extend(self._node_to_chunks(doc_id, node, []))
        return chunks

    def _build_heading_tree(self, markdown: str) -> list[dict]:
        lines = markdown.split("\n")
        root = []
        stack = [{"level": 0, "heading": "", "content": [], "children": [], "start": 0}]

        heading_pattern = re.compile(r"^(#{1,6})\s+(.+)$")
        for i, line in enumerate(lines):
            m = heading_pattern.match(line)
            if m:
                level = len(m.group(1))
                heading = m.group(2).strip()
                node = {"level": level, "heading": heading, "content": [], "children": [], "start": i}
                while stack and stack[-1]["level"] >= level:
                    stack.pop()
                if stack:
                    stack[-1]["children"].append(node)
                else:
                    root.append(node)
                stack.append(node)
            else:
                if stack:
                    stack[-1]["content"].append(line)

        placeholder = stack[0]
        if placeholder.get("content"):
            root.append(placeholder)
        for child in placeholder.get("children", []):
            root.append(child)

        return root

    def _node_to_chunks(self, doc_id: str, node: dict, parent_headings: list[str]) -> list[dict]:
        chunks = []
        heading_path = parent_headings + [node["heading"]] if node["heading"] else parent_headings
        heading_str = " > ".join(h for h in heading_path if h)

        text = "\n".join(node["content"]).strip()
        if text:
            text_chunks = self._split_text(doc_id, text, heading_str)
            chunks.extend(text_chunks)

        for child in node.get("children", []):
            chunks.extend(self._node_to_chunks(doc_id, child, heading_path))

        return chunks

    def _split_text(self, doc_id: str, text: str, heading: str) -> list[dict]:
        splits = self._splitter.split_text(text)
        return [self._make_chunk(doc_id, s, heading, i) for i, s in enumerate(splits)]

    def _make_chunk(self, doc_id: str, text: str, heading: str, idx: int) -> dict:
        return {
            "doc_id": doc_id,
            "chunk_id": f"{doc_id}_chunk_{idx:04d}",
            "heading": heading,
            "text": text,
            "metadata": {"heading": heading, "chunk_index": idx},
        }
