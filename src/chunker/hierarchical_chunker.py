import re
from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter


ARTICLE_PATTERN = re.compile(r"第[零一二三四五六七八九十百千万0-9]+条")


class HierarchicalChunker:
    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 64):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=[
                "\n\n",
                "\n第",
                "\n",
                "。",
                "！",
                "？",
                "；",
                "，",
                "",
            ],
        )
        self._chunk_counter = 0

    def chunk(self, doc_id: str, markdown: str) -> list[dict[str, Any]]:
        self._chunk_counter = 0
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

        chapter = parent_headings[0] if parent_headings else ""
        article_num = _extract_article(heading_str)

        text = "\n".join(node["content"]).strip()
        if text:
            text_chunks = self._split_text(doc_id, text, heading_str, chapter, article_num)
            chunks.extend(text_chunks)

        for child in node.get("children", []):
            chunks.extend(self._node_to_chunks(doc_id, child, heading_path))

        return chunks

    def _split_text(self, doc_id: str, text: str, heading: str, chapter: str, heading_article: str) -> list[dict]:
        if not heading_article:
            heading_article = _extract_article(text[:128])
        splits = self._splitter.split_text(text)
        result = []
        for s in splits:
            article_num = heading_article or _extract_article(s[:256])
            result.append(self._make_chunk(doc_id, s, heading, chapter, article_num))
        return result

    def _make_chunk(self, doc_id: str, text: str, heading: str, chapter: str, article_num: str) -> dict:
        idx = self._chunk_counter
        self._chunk_counter += 1
        metadata = {
            "heading": heading,
            "chunk_index": idx,
        }
        if chapter:
            metadata["chapter"] = chapter
        if article_num:
            metadata["article_num"] = article_num
        return {
            "doc_id": doc_id,
            "chunk_id": f"{doc_id}_chunk_{idx:04d}",
            "heading": heading,
            "text": text,
            "metadata": metadata,
        }


def _extract_article(text: str) -> str:
    m = ARTICLE_PATTERN.search(text)
    return m.group(0) if m else ""
