import re
from typing import Any


class TableParser:
    @staticmethod
    def parse_html_table(html: str) -> dict[str, Any]:
        import html as html_mod
        headers = []
        rows = []
        caption = ""

        caption_match = re.search(r"<caption>(.*?)</caption>", html, re.DOTALL)
        if caption_match:
            caption = caption_match.group(1).strip()

        th_matches = re.findall(r"<th[^>]*>(.*?)</th>", html, re.DOTALL)
        if th_matches:
            headers = [html_mod.unescape(re.sub(r"<[^>]+>", "", h)).strip() for h in th_matches]

        tr_matches = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL)
        for tr in tr_matches:
            td_matches = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.DOTALL)
            if td_matches:
                rows.append([
                    html_mod.unescape(re.sub(r"<[^>]+>", "", td)).strip()
                    for td in td_matches
                ])

        return {
            "type": "table",
            "caption": caption,
            "headers": headers,
            "rows": rows,
            "num_rows": len(rows),
            "num_cols": max(len(h) if h else (len(rows[0]) if rows else 0) for h in [headers]) if (headers or rows) else 0,
        }

    @staticmethod
    def merge_cross_page_tables(tables: list[dict]) -> list[dict]:
        if not tables:
            return tables

        merged = [tables[0]]
        for table in tables[1:]:
            last = merged[-1]
            if (
                table.get("headers") == last.get("headers")
                and table.get("num_cols") == last.get("num_cols")
                and table.get("caption") == last.get("caption")
            ):
                last["rows"].extend(table["rows"])
                last["num_rows"] = len(last["rows"])
            else:
                merged.append(table)
        return merged

    @staticmethod
    def table_to_text(table: dict) -> str:
        parts = []
        if table.get("caption"):
            parts.append(f"[Table] {table['caption']}")
        if table.get("headers"):
            parts.append(" | ".join(table["headers"]))
            parts.append(" | ".join(["---"] * len(table["headers"])))
        for row in table.get("rows", []):
            parts.append(" | ".join(row))
        return "\n".join(parts)

    @staticmethod
    def extract_tables_from_markdown(markdown: str) -> list[dict]:
        tables = []
        lines = markdown.split("\n")
        i = 0
        while i < len(lines):
            if "|" in lines[i] and i + 1 < len(lines) and "---" in lines[i + 1]:
                headers = [h.strip() for h in lines[i].split("|") if h.strip()]
                rows = []
                i += 2
                while i < len(lines) and "|" in lines[i]:
                    cells = [c.strip() for c in lines[i].split("|") if c.strip()]
                    if cells:
                        rows.append(cells)
                    i += 1
                tables.append({
                    "type": "table",
                    "headers": headers,
                    "rows": rows,
                    "num_rows": len(rows),
                    "num_cols": len(headers),
                })
            else:
                i += 1
        return tables
