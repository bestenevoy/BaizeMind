from typing import Any


class ContextMerger:
    def __init__(self, max_merge_chars: int = 1500):
        self.max_merge_chars = max_merge_chars

    def merge(self, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not chunks:
            return chunks

        merged = [chunks[0]]
        for chunk in chunks[1:]:
            last = merged[-1]
            if self._should_merge(last, chunk):
                merged_len = len(last["text"]) + len(chunk["text"])
                if merged_len <= self.max_merge_chars:
                    last["text"] = last["text"] + "\n\n" + chunk["text"]
                    last["metadata"]["merged_chunks"] = last["metadata"].get("merged_chunks", [last["chunk_id"]]) + [chunk["chunk_id"]]
                    last["chunk_id"] = last["chunk_id"] + "+"
                    continue
            merged.append(chunk)

        return merged

    def _should_merge(self, a: dict, b: dict) -> bool:
        if a.get("doc_id") != b.get("doc_id"):
            return False
        if (
            a["metadata"].get("type") == "table"
            and b["metadata"].get("type") == "text"
        ):
            return True
        if (
            a["metadata"].get("type") == "text"
            and b["metadata"].get("type") == "table"
        ):
            return True
        if a.get("heading") and b.get("heading"):
            if a["heading"] == b["heading"]:
                return True
        if not b.get("heading"):
            return True
        return False

    def deduplicate(self, chunks: list[dict]) -> list[dict]:
        seen = set()
        result = []
        for chunk in chunks:
            text_hash = hash(chunk["text"][:100])
            if text_hash not in seen:
                seen.add(text_hash)
                result.append(chunk)
        return result
