"""文档解析模块测试"""


def test_table_parser_html():
    from src.document_parser.table_parser import TableParser
    html = "<table><caption>Test</caption><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
    result = TableParser.parse_html_table(html)
    assert result["caption"] == "Test"
    assert result["headers"] == ["A", "B"]
    assert len(result["rows"]) == 1


def test_table_parser_markdown():
    from src.document_parser.table_parser import TableParser
    md = "| A | B | C |\n| --- | --- | --- |\n| 1 | 2 | 3 |\n| 4 | 5 | 6 |\n\nNormal text."
    tables = TableParser.extract_tables_from_markdown(md)
    assert len(tables) == 1
    assert tables[0]["num_rows"] == 2
    assert tables[0]["num_cols"] == 3


def test_cross_page_merge():
    from src.document_parser.table_parser import TableParser
    t1 = {"headers": ["A", "B"], "rows": [["1", "2"]], "num_rows": 1, "num_cols": 2, "caption": "T1"}
    t2 = {"headers": ["A", "B"], "rows": [["3", "4"]], "num_rows": 1, "num_cols": 2, "caption": "T1"}
    merged = TableParser.merge_cross_page_tables([t1, t2])
    assert len(merged) == 1
    assert merged[0]["num_rows"] == 2
