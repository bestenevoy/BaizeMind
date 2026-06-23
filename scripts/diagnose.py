#!/usr/bin/env python3
"""分层诊断脚本 — 按服务依赖从低到高逐层测试。

用法:
  uv run python scripts/diagnose.py            # 全部测试
  uv run python scripts/diagnose.py --env      # 仅环境检查
  uv run python scripts/diagnose.py --services # 仅服务连通性
  uv run python scripts/diagnose.py --chunk    # 仅分块测试
  uv run python scripts/diagnose.py --embed    # 仅嵌入测试
  uv run python scripts/diagnose.py --milvus   # 仅 Milvus 测试
  uv run python scripts/diagnose.py --neo4j    # 仅 Neo4j 测试
  uv run python scripts/diagnose.py --parse    # 仅文档解析测试
  uv run python scripts/diagnose.py --agent    # 仅 Agent 测试（LLM）

分层：
  L0  环境配置  — .env 文件、必填 API Key
  L1  服务连通  — Milvus (:19530), Neo4j (:7687)
  L2  API 响应  — DeepSeek LLM 调用, SiliconFlow 嵌入
  L3  纯 Python 模块 — 分块器、文档存储（无外部依赖）
  L4  文档解析 — MinerU CLI（需 GPU/模型，耗时较长）
  L5  向量存储  — Milvus 写入/搜索
  L6  知识图谱  — Neo4j 连接/写入/查询
  L7  检索流程  — 混合检索（Milvus + BM25 + 嵌入 + 重排序）
  L8  Agent 流程 — 完整工作流（需要所有服务可用）
"""

import argparse
import sys
import time
from pathlib import Path

# 确保项目根目录在 Python path 中
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

# ── 颜色 ──────────────────────────────────────────────────────────────
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
BOLD = "\033[1m"
RESET = "\033[0m"


def ok(msg: str) -> str:
    return f"  {GREEN}✓{RESET} {msg}"


def fail(msg: str) -> str:
    return f"  {RED}✗{RESET} {msg}"


def warn(msg: str) -> str:
    return f"  {YELLOW}⚠{RESET} {msg}"


def title(msg: str) -> str:
    return f"\n{BOLD}{BLUE}{'─' * 60}{RESET}\n{BOLD}{msg}{RESET}\n{BOLD}{BLUE}{'─' * 60}{RESET}"


# ── L0: 环境配置 ──────────────────────────────────────────────────────


def check_env() -> bool:
    """检查 .env 文件及必填配置项。"""
    print(title("L0  环境配置检查"))

    all_ok = True
    env_file = _project_root / ".env"

    if env_file.exists():
        print(ok(f".env 文件存在: {env_file}"))
    else:
        print(fail(f".env 文件不存在: {env_file}"))
        print(warn("  → 复制 .env.example 为 .env 并填写配置"))
        all_ok = False

    # 加载 settings 检查关键值
    try:
        from config.settings import settings  # noqa: C0415

        checks = [
            ("DEEPSEEK_API_KEY", settings.deepseek_api_key, "DeepSeek API Key"),
            ("SILICONFLOW_API_KEY", settings.siliconflow_api_key, "SiliconFlow API Key"),
            ("NEO4J_PASSWORD", settings.neo4j_password, "Neo4j 密码"),
        ]
        for key, value, label in checks:
            if value:
                print(ok(f"{label} 已配置 ({key})"))
            else:
                print(fail(f"{label} 未配置 ({key})"))
                all_ok = False

        # 可选但建议检查
        optional = [
            ("MILVUS_HOST", settings.milvus_host, "Milvus 地址"),
            ("MILVUS_PORT", settings.milvus_port, "Milvus 端口"),
            ("NEO4J_URI", settings.neo4j_uri, "Neo4j URI"),
        ]
        for key, value, label in optional:
            print(ok(f"{label}: {value}"))
    except Exception as e:
        print(fail(f"加载配置失败: {e}"))
        all_ok = False

    return all_ok


# ── L1: 服务连通性 ────────────────────────────────────────────────────


def check_services() -> bool:
    """检查 Milvus 和 Neo4j 是否可达。"""
    print(title("L1  服务连通性检查"))

    milvus_ok = _check_milvus_port()
    neo4j_ok = _check_neo4j_port()

    if not milvus_ok:
        print(warn("  → Milvus 未运行，启动方式:"))
        print(warn("    bash scripts/setup_milvus.sh"))
    if not neo4j_ok:
        print(warn("  → Neo4j 未运行，启动方式:"))
        print(warn("    docker run -d --name neo4j -p 7474:7474 -p 7687:7687 \\"))
        print(warn("      -e NEO4J_AUTH=neo4j/your_password neo4j:5"))

    return milvus_ok and neo4j_ok


def _check_milvus_port() -> bool:
    import socket

    try:
        from config.settings import settings  # noqa: C0415

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        result = s.connect_ex((settings.milvus_host, settings.milvus_port))
        s.close()
        if result == 0:
            # 再试试用 pymilvus 连接
            try:
                from pymilvus import MilvusClient  # noqa: C0415

                client = MilvusClient(uri=f"http://{settings.milvus_host}:{settings.milvus_port}")
                client.list_collections()
                print(ok(f"Milvus 连接成功 ({settings.milvus_host}:{settings.milvus_port})"))
                return True
            except Exception:
                print(
                    fail(
                        f"Milvus 端口可达但 pymilvus 无法连接 ({settings.milvus_host}:{settings.milvus_port})"
                    )
                )
                return False
        else:
            print(fail(f"Milvus 端口不可达 ({settings.milvus_host}:{settings.milvus_port})"))
            return False
    except Exception as e:
        print(fail(f"Milvus 检查异常: {e}"))
        return False


def _check_neo4j_port() -> bool:
    import socket

    try:
        from config.settings import settings  # noqa: C0415

        # 解析 bolt URI
        uri = settings.neo4j_uri.replace("bolt://", "")
        host, _, port_str = uri.partition(":")
        port = int(port_str) if port_str else 7687

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        result = s.connect_ex((host, port))
        s.close()
        if result == 0:
            # 再试试用 neo4j driver 连接
            try:
                from neo4j import GraphDatabase  # noqa: C0415

                driver = GraphDatabase.driver(
                    settings.neo4j_uri,
                    auth=(settings.neo4j_user, settings.neo4j_password),
                )
                driver.verify_connectivity()
                driver.close()
                print(ok(f"Neo4j 连接成功 ({settings.neo4j_uri})"))
                return True
            except Exception as e2:
                print(fail(f"Neo4j 端口可达但 driver 认证失败 ({settings.neo4j_uri}): {e2}"))
                return False
        else:
            print(fail(f"Neo4j 端口不可达 ({settings.neo4j_uri})"))
            return False
    except Exception as e:
        print(fail(f"Neo4j 检查异常: {e}"))
        return False


# ── L2: API 响应 ───────────────────────────────────────────────────────


def check_apis() -> bool:
    """检查 DeepSeek LLM 和 SiliconFlow 嵌入 API 是否可用。"""
    print(title("L2  API 响应检查"))

    ds_ok = _check_deepseek_llm()
    sf_ok = _check_siliconflow_embed()

    return ds_ok and sf_ok


def _check_deepseek_llm() -> bool:
    try:
        from src.llm.deepseek import get_chat_llm  # noqa: C0415

        llm = get_chat_llm(temperature=0.0)
        resp = llm.invoke("回复'OK'，不要其他内容")
        text = resp.content if hasattr(resp, "content") else str(resp)
        if "OK" in text:
            print(ok(f"DeepSeek LLM 调用成功 → {text.strip()}"))
            return True
        else:
            print(fail(f"DeepSeek LLM 返回异常: {text[:100]}"))
            return False
    except Exception as e:
        print(fail(f"DeepSeek LLM 调用失败: {e}"))
        return False


def _check_siliconflow_embed() -> bool:
    try:
        from src.embeddings.bge_m3 import BGEM3Embedding  # noqa: C0415

        emb = BGEM3Embedding(use_local=False)
        vec = emb.encode_query_dense("测试文本")
        if vec.shape == (1024,):
            print(ok(f"SiliconFlow 嵌入调用成功 → 向量维度 {vec.shape[0]}"))
            return True
        else:
            print(fail(f"SiliconFlow 嵌入维度异常: {vec.shape}"))
            return False
    except Exception as e:
        print(fail(f"SiliconFlow 嵌入调用失败: {e}"))
        return False


# ── L3: 纯 Python 模块 ─────────────────────────────────────────────────


def check_python_modules() -> bool:
    """测试无需外部服务的纯 Python 模块。"""
    print(title("L3  纯 Python 模块测试"))

    results = [
        _check_chunker(),
        _check_doc_store(),
    ]
    return all(results)


def _check_chunker() -> bool:
    try:
        from src.chunker.hierarchical_chunker import HierarchicalChunker  # noqa: C0415

        markdown = """# 第一章
这是第一段内容，用于测试分块功能。

## 1.1 小节
这是第一小节的内容，包含一些技术描述。

## 1.2 小节
这是第二小节的内容，继续测试。
"""
        chunker = HierarchicalChunker(chunk_size=256, chunk_overlap=32)
        chunks = chunker.chunk("test_doc", markdown)
        if len(chunks) == 0:
            print(fail("分块结果为空"))
            return False
        # 验证 chunk 结构
        c = chunks[0]
        required_keys = {"doc_id", "chunk_id", "text"}
        missing = required_keys - set(c.keys())
        if missing:
            print(fail(f"分块结果缺少字段: {missing}"))
            return False
        print(ok(f"分块器测试通过 → {len(chunks)} 个 chunk"))
        return True
    except Exception as e:
        print(fail(f"分块器测试失败: {e}"))
        return False


def _check_doc_store() -> bool:
    try:
        import src.storage.doc_store as ds  # noqa: C0415

        test_id = "_diag_test_doc"
        ds.delete_document(test_id)
        doc = ds.create_document(test_id, "diagnose_test.txt", folder="/")
        assert doc["doc_id"] == test_id, "doc_id mismatch"

        ds.update_document(test_id, status="completed", chunk_count=5)
        doc = ds.get_document(test_id)
        assert doc and doc["status"] == "completed", "status update failed"

        # 测试文件夹和标签
        ds.add_tag(test_id, "测试")
        tags = ds.list_all_tags()
        doc_with_filter = ds.get_doc_ids_by_filter(folder="/", tags=["测试"])
        assert test_id in doc_with_filter, "tag filter failed"

        ds.delete_document(test_id)
        print(ok("文档存储 (SQLite) 测试通过"))
        return True
    except Exception as e:
        print(fail(f"文档存储测试失败: {e}"))
        return False


# ── L4: 文档解析 ───────────────────────────────────────────────────────


def check_parser(test_file: str | None = None) -> bool:
    """测试 MinerU 文档解析（需要 GPU/模型，耗时较长）。"""
    print(title("L4  文档解析测试（MinerU）"))

    if test_file is None:
        print(warn("  未指定测试文件，跳过（使用 --test-file 指定）"))
        print(warn("  → 示例: uv run python scripts/diagnose.py --parse --test-file doc.pdf"))
        return True  # 不算失败

    test_path = Path(test_file)
    if not test_path.exists():
        print(fail(f"测试文件不存在: {test_file}"))
        return False

    try:
        from src.document_parser.mineru_parser import MinerUParser  # noqa: C0415

        print(ok(f"开始解析: {test_path}"))
        start = time.time()
        result = MinerUParser(model_source="modelscope").parse(str(test_path))
        elapsed = time.time() - start
        print(
            ok(
                f"解析成功 ({elapsed:.1f}s) → markdown {len(result['markdown'])} 字符, "
                f"content_list {len(result['content_list'])} 条"
            )
        )

        # 也测试 OcrParser（如果文件是图片类型）
        ext = test_path.suffix.lower()
        if ext in (".jpg", ".jpeg", ".png", ".bmp", ".tiff"):
            print(ok("检测到图片文件，跳过 PaddleOCR 测试（需额外配置）"))

        return True
    except Exception as e:
        print(fail(f"文档解析失败: {e}"))
        return False


# ── L5: 向量存储 ───────────────────────────────────────────────────────


def check_milvus() -> bool:
    """测试 Milvus 写入和搜索。"""
    print(title("L5  Milvus 向量存储测试"))

    try:
        from src.embeddings.bge_m3 import BGEM3Embedding  # noqa: C0415
        from src.retrieval.vector_retriever import MilvusVectorRetriever  # noqa: C0415

        retriever = MilvusVectorRetriever()
        retriever.connect()
        retriever.ensure_collection()

        # 写入测试数据
        test_doc_id = "_diag_milvus_test"
        test_chunks = [
            {"doc_id": test_doc_id, "chunk_id": f"{test_doc_id}_0", "text": "Python 是一种编程语言"},
            {"doc_id": test_doc_id, "chunk_id": f"{test_doc_id}_1", "text": "Java 企业级开发"},
        ]

        emb_model = BGEM3Embedding(use_local=False)
        embeddings = emb_model.encode_dense([c["text"] for c in test_chunks])

        # 先清理再写入
        try:
            retriever.delete_by_doc(test_doc_id)
        except Exception:
            pass

        retriever.insert(test_chunks, embeddings)
        count = retriever.count()
        print(ok(f"Milvus 写入成功 → 集合文档数: {count}"))

        # 搜索测试
        query_vec = emb_model.encode_query_dense("Python 编程")
        results = retriever.search(query_vec, top_k=2)
        if len(results) == 0:
            print(fail("Milvus 搜索返回空结果"))
            return False

        print(ok(f"Milvus 搜索成功 → top result: {results[0]['text'][:50]}"))

        # 清理
        retriever.delete_by_doc(test_doc_id)
        return True
    except Exception as e:
        print(fail(f"Milvus 测试失败: {e}"))
        return False


# ── L6: 知识图谱 ───────────────────────────────────────────────────────


def check_neo4j() -> bool:
    """测试 Neo4j 连接、schema 初始化和基本操作。"""
    print(title("L6  Neo4j 知识图谱测试"))

    try:
        from src.knowledge_graph.neo4j_manager import Neo4jManager  # noqa: C0415
        from src.knowledge_graph.entity_extractor import EntityExtractor  # noqa: C0415
        from src.knowledge_graph.evidence import EntityEvidence, make_entity_key  # noqa: C0415

        neo4j = Neo4jManager()
        neo4j.connect()
        neo4j.init_evidence_schema()

        # 清理之前测试数据
        neo4j.query("MATCH (n {source: '_diagnose_test'}) DETACH DELETE n")

        # 插入测试实体 (evidence model)
        entity_key = make_entity_key("ProgrammingLanguage", "Python")
        neo4j.sync_entity_with_name(entity_key, "Python", "ProgrammingLanguage", 1)
        neo4j.query("MATCH (e:Entity {entity_key: $k}) SET e.source = '_diagnose_test'", {"k": entity_key})

        # 查询
        stats = neo4j.get_stats()
        print(ok(f"Neo4j 连接成功 → 实体: {stats['entity_count']}, Fact: {stats['fact_count']}"))

        neighbors = neo4j.get_neighbors("Python", max_hops=1)
        print(ok(f"Neo4j 邻居查询成功 → {len(neighbors)} 条记录"))

        # 测试证据抽取（需要 DeepSeek API）
        try:
            extractor = EntityExtractor()
            items = extractor.extract_evidence("苹果公司在1984年推出了Macintosh电脑。")
            if len(items) > 0:
                print(ok(f"证据抽取测试通过 → 抽取到 {len(items)} 条证据"))
            else:
                print(warn("证据抽取返回空结果（可能是 LLM 未响应）"))
        except Exception as e:
            print(warn(f"证据抽取跳过（LLM 调用失败）: {e}"))

        # 清理
        neo4j.query("MATCH (n {source: '_diagnose_test'}) DETACH DELETE n")
        neo4j.close()
        return True
    except Exception as e:
        print(fail(f"Neo4j 测试失败: {e}"))
        return False


# ── L7: 检索流程 ───────────────────────────────────────────────────────


def check_retrieval() -> bool:
    """测试混合检索流程（需要 Milvus + 嵌入 API）。"""
    print(title("L7  混合检索流程测试"))

    try:
        from src.retrieval.hybrid_retriever import HybridRetriever  # noqa: C0415
        from src.retrieval.bm25_retriever import BM25Retriever  # noqa: C0415

        # 1. BM25 纯本地测试
        bm25 = BM25Retriever()
        chunks = [
            {"doc_id": "d1", "chunk_id": "c1", "text": "Python is a programming language", "metadata": {}},
            {"doc_id": "d1", "chunk_id": "c2", "text": "Java is also a programming language", "metadata": {}},
            {"doc_id": "d2", "chunk_id": "c3", "text": "Machine learning with Python", "metadata": {}},
        ]
        bm25.build_index(chunks)
        results = bm25.search("Python programming")
        assert len(results) > 0
        print(ok(f"BM25 检索测试通过 → top: {results[0]['text'][:40]}"))

        # 2. Hybrid 测试（需要 Milvus）
        try:
            hybrid = HybridRetriever()
            results = hybrid.retrieve("Python programming", top_k=3)
            if len(results) > 0:
                print(ok(f"混合检索测试通过 → {len(results)} 条结果"))
            else:
                print(warn("混合检索返回空结果（Milvus 中可能无数据）"))
        except Exception as e:
            print(warn(f"混合检索跳过（Milvus 不可用或数据不足）: {e}"))

        return True
    except Exception as e:
        print(fail(f"检索测试失败: {e}"))
        return False


# ── L8: Agent 流程 ─────────────────────────────────────────────────────


def check_agent() -> bool:
    """测试 Agent 工作流（LLM 调用 + 各项服务）。"""
    print(title("L8  Agent 工作流测试"))

    try:
        from src.agents.workflow import AgenticRAGWorkflow  # noqa: C0415

        wf = AgenticRAGWorkflow()

        # 1. 闲聊测试（不需要检索/图谱）
        result = wf.invoke("你好，请回复'OK'", folder="/")
        query_type = result.get("query_type", "?")
        final_answer = result.get("final_answer", "")
        print(ok(f"Agent 闲聊测试 → query_type={query_type}, answer='{final_answer[:50]}'"))

        # 2. 简单事实查询（需要检索）
        try:
            result = wf.invoke("什么是机器学习？", folder="/")
            query_type = result.get("query_type", "?")
            docs_count = len(result.get("documents", []))
            print(ok(f"Agent 事实查询 → query_type={query_type}, 检索到 {docs_count} 篇文档"))
        except Exception as e:
            print(warn(f"Agent 事实查询跳过（检索不可用）: {e}"))

        return True
    except Exception as e:
        print(fail(f"Agent 测试失败: {e}"))
        return False


# ── 主入口 ──────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Agentic-GraphRAG 分层诊断工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--env", action="store_true", help="仅 L0 环境检查")
    parser.add_argument("--services", action="store_true", help="仅 L1 服务连通性")
    parser.add_argument("--apis", action="store_true", help="仅 L2 API 响应")
    parser.add_argument("--modules", action="store_true", help="仅 L3 纯 Python 模块")
    parser.add_argument("--parse", action="store_true", help="仅 L4 文档解析")
    parser.add_argument("--milvus", action="store_true", help="仅 L5 Milvus 存储")
    parser.add_argument("--neo4j", action="store_true", help="仅 L6 Neo4j 图谱")
    parser.add_argument("--retrieval", action="store_true", help="仅 L7 检索流程")
    parser.add_argument("--agent", action="store_true", help="仅 L8 Agent 流程")
    parser.add_argument("--test-file", type=str, help="L4 文档解析测试文件路径")
    parser.add_argument("--quick", action="store_true", help="快速诊断（跳过耗时测试 L4/L8）")

    args = parser.parse_args()

    # 如果没有指定任何选项，运行全部
    run_all = not any(
        [args.env, args.services, args.apis, args.modules, args.parse, args.milvus, args.neo4j, args.retrieval, args.agent]
    )

    print(f"\n{BOLD}{'=' * 60}{RESET}")
    print(f"{BOLD}  Agentic-GraphRAG 诊断工具{RESET}")
    print(f"{BOLD}{'=' * 60}{RESET}")

    results = {}

    if run_all or args.env:
        results["L0 环境配置"] = check_env()

    if run_all or args.services:
        results["L1 服务连通"] = check_services()

    if run_all or args.apis:
        results["L2 API 响应"] = check_apis()

    if run_all or args.modules:
        results["L3 Python 模块"] = check_python_modules()

    if args.parse:
        results["L4 文档解析"] = check_parser(args.test_file)
    elif run_all and not args.quick:
        results["L4 文档解析"] = check_parser(None)

    if run_all or args.milvus:
        results["L5 Milvus 存储"] = check_milvus()

    if run_all or args.neo4j:
        results["L6 Neo4j 图谱"] = check_neo4j()

    if run_all or args.retrieval:
        results["L7 检索流程"] = check_retrieval()

    if args.agent:
        results["L8 Agent 流程"] = check_agent()
    elif run_all and not args.quick:
        results["L8 Agent 流程"] = check_agent()

    # ── 汇总 ────────────────────────────────────────────────────────
    print(title("诊断汇总"))
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    for name, ok_ in results.items():
        status = f"{GREEN}PASS{RESET}" if ok_ else f"{RED}FAIL{RESET}"
        print(f"  [{status}]  {name}")

    print(f"\n  {passed}/{total} 项通过")

    if passed < total:
        print(f"\n  {YELLOW}提示: 从 L0 开始向下排查，上层依赖下层。{RESET}")
        print(f"  {YELLOW}例如: 检索失败先检查 L2 (API) 和 L5 (Milvus) 是否通过。{RESET}")
        sys.exit(1)
    else:
        print(f"  {GREEN}所有检测项通过！系统可以正常使用。{RESET}")


if __name__ == "__main__":
    main()
