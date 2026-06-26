"""Excel RAG: RAG + NL2SQL hybrid for standardized Excel reports.

职责划分：
- 向量库负责定位目标表（按 Sheet 摘要语义检索）
- 元数据负责约束 SQL 生成（Schema / 字段映射 / 类型）
- SQLite 负责精确计算（明细数据入库后执行 SQL）
- LLM 负责理解问题与组织回答（生成 SQL + 自然语言回答）

子模块：
- parser: Excel 解析（表头提取、统计信息、类型推断）
- summarizer: LLM 生成摘要 + 中英文字段映射
- store: SQLite 元数据 + 动态数据表
- vector_store: Milvus 摘要向量检索
- nl2sql: SQL 生成 / 校验 / 执行 / 自动修正
- pipeline: 入库编排
- qa: 查询编排（召回 → 元数据 → NL2SQL → 执行 → 回答）
"""
