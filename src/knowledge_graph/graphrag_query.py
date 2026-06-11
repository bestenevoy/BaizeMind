import asyncio
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from config.settings import settings


class GraphRAGQuery:
    def __init__(self, root_dir: Optional[str] = None, community_level: int = 2):
        self.root_dir = Path(root_dir or settings.graphrag_root_dir)
        self.output_dir = self.root_dir / "output"
        self.community_level = community_level
        self._global_search = None
        self._local_search = None
        self._drift_search = None

    def _load_parquet(self, table_name: str) -> pd.DataFrame:
        candidates = list(self.output_dir.rglob(f"{table_name}.parquet"))
        if not candidates:
            raise FileNotFoundError(f"Table '{table_name}' not found in {self.output_dir}")
        return pd.read_parquet(candidates[0])

    def _build_model(self, name: str):
        from graphrag.config.enums import ModelType
        from graphrag.config.models.language_model_config import LanguageModelConfig
        from graphrag.language_model.manager import ModelManager

        config = LanguageModelConfig(
            api_key=settings.deepseek_api_key,
            type=ModelType.Chat,
            model_provider="openai",
            model=settings.deepseek_chat_model,
            api_base=settings.deepseek_base_url,
            max_retries=5,
        )
        return ModelManager().get_or_create_chat_model(
            name=name,
            model_type=ModelType.Chat,
            config=config,
        )

    def _get_tokenizer(self):
        from graphrag.config.enums import ModelType
        from graphrag.config.models.language_model_config import LanguageModelConfig
        from graphrag.tokenizer.get_tokenizer import get_tokenizer

        config = LanguageModelConfig(
            api_key=settings.deepseek_api_key,
            type=ModelType.Chat,
            model_provider="openai",
            model=settings.deepseek_chat_model,
            api_base=settings.deepseek_base_url,
        )
        return get_tokenizer(config)

    def _init_global_search(self):
        if self._global_search is not None:
            return

        from graphrag.query.indexer_adapters import (
            read_indexer_communities,
            read_indexer_entities,
            read_indexer_reports,
        )
        from graphrag.query.structured_search.global_search.community_context import (
            GlobalCommunityContext,
        )
        from graphrag.query.structured_search.global_search.search import GlobalSearch

        community_df = self._load_parquet("communities")
        entity_df = self._load_parquet("entities")
        report_df = self._load_parquet("community_reports")

        communities = read_indexer_communities(community_df, report_df)
        reports = read_indexer_reports(report_df, community_df, self.community_level)
        entities = read_indexer_entities(entity_df, community_df, self.community_level)

        tokenizer = self._get_tokenizer()
        model = self._build_model("global_search")

        context_builder = GlobalCommunityContext(
            community_reports=reports,
            communities=communities,
            entities=entities,
            tokenizer=tokenizer,
        )

        self._global_search = GlobalSearch(
            model=model,
            context_builder=context_builder,
            tokenizer=tokenizer,
            max_data_tokens=12000,
            map_llm_params={"max_tokens": 1000, "temperature": 0.0},
            reduce_llm_params={"max_tokens": 2000, "temperature": 0.0},
            allow_general_knowledge=False,
            json_mode=False,
            context_builder_params={
                "use_community_summary": False,
                "shuffle_data": True,
                "include_community_rank": True,
                "min_community_rank": 0,
                "community_rank_name": "rank",
                "include_community_weight": True,
                "community_weight_name": "occurrence weight",
                "normalize_community_weight": True,
                "max_tokens": 12000,
                "context_name": "Reports",
            },
            concurrent_coroutines=8,
            response_type="multiple paragraphs",
        )

    def _init_local_search(self):
        if self._local_search is not None:
            return

        from graphrag.query.indexer_adapters import (
            read_indexer_covariates,
            read_indexer_entities,
            read_indexer_relationships,
            read_indexer_reports,
            read_indexer_text_units,
        )
        from graphrag.query.structured_search.local_search.mixed_context import (
            LocalSearchMixedContext,
        )
        from graphrag.query.structured_search.local_search.search import LocalSearch
        from graphrag.vector_stores.lancedb import LanceDBVectorStore

        entity_df = self._load_parquet("entities")
        community_df = self._load_parquet("communities")
        report_df = self._load_parquet("community_reports")
        relationship_df = self._load_parquet("relationships")
        text_unit_df = self._load_parquet("text_units")

        entities = read_indexer_entities(entity_df, community_df, self.community_level)
        relationships = read_indexer_relationships(relationship_df)
        reports = read_indexer_reports(report_df, community_df, self.community_level)
        text_units = read_indexer_text_units(text_unit_df)

        covariates = None
        try:
            covariate_df = self._load_parquet("covariates")
            covariates = read_indexer_covariates(covariate_df)
        except FileNotFoundError:
            pass

        tokenizer = self._get_tokenizer()
        model = self._build_model("local_search")

        description_embedding_store = LanceDBVectorStore(
            uri=str(self.output_dir / "lancedb"),
            table_name="entity_description_embeddings",
        )
        description_embedding_store.connect()

        context_builder = LocalSearchMixedContext(
            community_reports=reports,
            text_units=text_units,
            entities=entities,
            relationships=relationships,
            covariates=covariates,
            entity_text_embeddings=description_embedding_store,
            embedding_vectorstore_key="entity_description_embeddings",
            tokenizer=tokenizer,
        )

        self._local_search = LocalSearch(
            model=model,
            context_builder=context_builder,
            tokenizer=tokenizer,
            response_type="multiple paragraphs",
            max_llm_tokens=12000,
            context_builder_params={
                "text_unit_prop": 0.5,
                "community_prop": 0.1,
                "conversation_history_max_turns": 5,
                "conversation_history_user_turns_only": True,
                "top_k_mapped_entities": 10,
                "top_k_relationships": 10,
                "include_entity_rank": True,
                "include_relationship_weight": True,
                "include_community_rank": False,
                "return_candidate_context": False,
                "max_tokens": 12000,
            },
        )

    def _init_drift_search(self):
        if self._drift_search is not None:
            return

        from graphrag.query.indexer_adapters import (
            read_indexer_entities,
            read_indexer_reports,
            read_indexer_text_units,
        )
        from graphrag.query.structured_search.drift_search.drift_context import (
            DRIFTSearchContextBuilder,
        )
        from graphrag.query.structured_search.drift_search.search import DRIFTSearch
        from graphrag.vector_stores.lancedb import LanceDBVectorStore

        entity_df = self._load_parquet("entities")
        community_df = self._load_parquet("communities")
        report_df = self._load_parquet("community_reports")
        text_unit_df = self._load_parquet("text_units")

        entities = read_indexer_entities(entity_df, community_df, self.community_level)
        reports = read_indexer_reports(report_df, community_df, self.community_level)
        text_units = read_indexer_text_units(text_unit_df)

        tokenizer = self._get_tokenizer()
        model = self._build_model("drift_search")

        text_embedding_store = LanceDBVectorStore(
            uri=str(self.output_dir / "lancedb"),
            table_name="text_units",
        )
        text_embedding_store.connect()

        description_embedding_store = LanceDBVectorStore(
            uri=str(self.output_dir / "lancedb"),
            table_name="entity_description_embeddings",
        )
        description_embedding_store.connect()

        context_builder = DRIFTSearchContextBuilder(
            chat_model=model,
            text_embedder=self._build_embedding_model(),
            entities=entities,
            reports=reports,
            entity_text_embeddings=description_embedding_store,
            text_units=text_units,
            text_unit_embeddings=text_embedding_store,
            token_encoder=tokenizer,
        )

        self._drift_search = DRIFTSearch(
            model=model,
            context_builder=context_builder,
            tokenizer=tokenizer,
            response_type="multiple paragraphs",
        )

    def _build_embedding_model(self):
        from graphrag.config.enums import ModelType
        from graphrag.config.models.language_model_config import LanguageModelConfig
        from graphrag.language_model.manager import ModelManager

        config = LanguageModelConfig(
            api_key=settings.siliconflow_api_key,
            type=ModelType.Embedding,
            model_provider="openai",
            model=settings.siliconflow_embedding_model,
            api_base=settings.siliconflow_embedding_url.rsplit("/", 1)[0],
        )
        return ModelManager().get_or_create_embedding_model(
            name="graphrag_embedding",
            model_type=ModelType.Embedding,
            config=config,
        )

    async def global_search(self, query: str) -> dict[str, Any]:
        self._init_global_search()
        result = await self._global_search.search(query)
        return {
            "answer": result.response,
            "context_data": result.context_data,
            "llm_calls": result.llm_calls,
            "prompt_tokens": result.prompt_tokens,
            "output_tokens": result.output_tokens,
            "search_mode": "global",
        }

    async def local_search(self, query: str) -> dict[str, Any]:
        self._init_local_search()
        result = await self._local_search.search(query)
        return {
            "answer": result.response,
            "context_data": result.context_data,
            "llm_calls": result.llm_calls,
            "prompt_tokens": result.prompt_tokens,
            "output_tokens": result.output_tokens,
            "search_mode": "local",
        }

    async def drift_search(self, query: str) -> dict[str, Any]:
        self._init_drift_search()
        result = await self._drift_search.search(query)
        return {
            "answer": result.response,
            "context_data": result.context_data,
            "llm_calls": result.llm_calls,
            "prompt_tokens": result.prompt_tokens,
            "output_tokens": result.output_tokens,
            "search_mode": "drift",
        }

    def search_sync(self, query: str, mode: str = "global") -> dict[str, Any]:
        if mode == "global":
            return asyncio.run(self.global_search(query))
        elif mode == "local":
            return asyncio.run(self.local_search(query))
        elif mode == "drift":
            return asyncio.run(self.drift_search(query))
        else:
            raise ValueError(f"Unknown search mode: {mode}")
