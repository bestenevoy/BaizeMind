from typing import Any


class TableChunker:
    def __init__(self, max_table_rows: int = 30):
        self.max_table_rows = max_table_rows

    def chunk_tables(self, doc_id: str, tables: list[dict]) -> list[dict[str, Any]]:
        chunks = []
        for i, table in enumerate(tables):
            chunks.extend(self._chunk_single_table(doc_id, table, i))
        return chunks

    def _chunk_single_table(self, doc_id: str, table: dict, idx: int) -> list[dict]:
        caption = table.get("caption", "")
        headers = table.get("headers", [])
        rows = table.get("rows", [])
        header_line = " | ".join(headers) if headers else ""
        caption_line = f"[Table] {caption}" if caption else ""

        if len(rows) <= self.max_table_rows:
            return [
                self._make_chunk(doc_id, table, idx, 0)
            ]

        chunks = []
        for start in range(0, len(rows), self.max_table_rows):
            chunk_rows = rows[start : start + self.max_table_rows]
            chunk_table = {
                "type": "table",
                "caption": caption,
                "headers": headers,
                "rows": chunk_rows,
                "num_rows": len(chunk_rows),
                "num_cols": len(headers),
                "row_range": f"{start}-{start + len(chunk_rows) - 1}",
            }
            chunks.append(self._make_chunk(doc_id, chunk_table, idx, start // self.max_table_rows))

        return chunks

    def _make_chunk(self, doc_id: str, table: dict, table_idx: int, part_idx: int) -> dict:
        return {
            "doc_id": doc_id,
            "chunk_id": f"{doc_id}_table_{table_idx:03d}_part_{part_idx:03d}",
            "heading": table.get("caption", f"Table {table_idx}"),
            "text": self._table_to_text(table),
            "metadata": {
                "type": "table",
                "table_index": table_idx,
                "part_index": part_idx,
                "num_rows": table.get("num_rows", 0),
                "num_cols": table.get("num_cols", 0),
            },
        }

    @staticmethod
    def _table_to_text(table: dict) -> str:
        parts = []
        if table.get("caption"):
            parts.append(f"[Table] {table['caption']}")
        if table.get("headers"):
            parts.append(" | ".join(table["headers"]))
            parts.append(" | ".join(["---"] * len(table["headers"])))
        for row in table.get("rows", []):
            parts.append(" | ".join(row))
        return "\n".join(parts)
