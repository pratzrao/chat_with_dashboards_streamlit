import chromadb
from chromadb.config import Settings
from typing import List, Dict, Any
from retrieval.ingest import Document, DocumentIngester
from db.dbt_helpers import DbtHelper
from config import config
import os
import logging
import math
import re
import hashlib
import json
from openai import OpenAI

logger = logging.getLogger(__name__)

class LocalHashEmbeddingFunction:
    """Lightweight, deterministic embedding to avoid onnx runtime issues."""
    def __init__(self, dim: int = 256):
        self.dim = dim

    def __call__(self, input: List[str]) -> List[List[float]]:
        embeddings: List[List[float]] = []
        for text in input:
            tokens = re.findall(r"[a-zA-Z0-9_]+", (text or "").lower())
            vec = [0.0] * self.dim
            for tok in tokens:
                h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
                idx = h % self.dim
                vec[idx] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            vec = [v / norm for v in vec]
            embeddings.append(vec)
        return embeddings


class OpenAIEmbeddingFunction:
    """Semantic embeddings via OpenAI with simple disk cache."""

    def __init__(self, model: str = "text-embedding-3-small", cache_path: str = "dalgo_chat_dashboard/storage/embedding_cache.json"):
        self.model = model
        self.cache_path = cache_path
        self.client = OpenAI(api_key=config.openai_api_key)
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        try:
            with open(cache_path, "r") as f:
                self.cache = json.load(f)
        except Exception:
            self.cache = {}

    def __call__(self, input: List[str]) -> List[List[float]]:
        # Preserve order; fetch missing, cache results
        missing = [t for t in input if t not in self.cache]
        if missing:
            resp = self.client.embeddings.create(model=self.model, input=missing)
            for text, emb in zip(missing, resp.data):
                self.cache[text] = emb.embedding
            with open(self.cache_path, "w") as f:
                json.dump(self.cache, f)

        return [self.cache[t] for t in input]

class VectorStore:
    def __init__(self):
        # Create persistent storage directory
        self.persist_dir = "dalgo_chat_dashboard/storage/chroma_db"
        os.makedirs(self.persist_dir, exist_ok=True)
        # Silence chroma telemetry warnings
        os.environ.setdefault("CHROMADB_DISABLE_TELEMETRY", "1")

        # Use semantic embeddings only (OpenAI required)
        if not config.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for semantic embeddings.")
        self.embedding_fn = OpenAIEmbeddingFunction()
        
        self.client = chromadb.PersistentClient(
            path=self.persist_dir,
            settings=Settings(
                allow_reset=True,
                anonymized_telemetry=False
            )
        )
        
        self.collection_name = "dashboard_docs"
        try:
            self.collection = self.client.get_collection(
                name=self.collection_name,
                embedding_function=self.embedding_fn
            )
            logger.info(f"Loaded existing collection with {self.collection.count()} documents")
        except Exception:
            # Collection doesn't exist, will be created during ingestion
            self.collection = None
            logger.info("No existing collection found, will create new one")
    
    def ingest_documents(self, documents: List[Document]):
        """Ingest documents into the vector store, skipping rebuild if unchanged."""
        # Keep all schemas (including dev/intermediate) to preserve semantic matches across programs

        digest = self._compute_digest(documents)
        digest_path = os.path.join(self.persist_dir, "ingest_hash.txt")
        old_digest = None
        if os.path.exists(digest_path):
            with open(digest_path, "r") as f:
                old_digest = f.read().strip()

        if old_digest == digest and self.collection is not None:
            logger.info("Vector store unchanged; skipping re-ingest")
            return

        if self.collection is not None:
            # Delete existing collection to rebuild
            self.client.delete_collection(name=self.collection_name)
        
        self.collection = self.client.create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
            embedding_function=self.embedding_fn
        )
        
        # Prepare data for ChromaDB
        doc_ids = [doc.doc_id for doc in documents]
        contents = [doc.content for doc in documents]
        metadatas = [doc.metadata for doc in documents]
        
        # Add documents to collection
        self.collection.add(
            documents=contents,
            metadatas=metadatas,
            ids=doc_ids
        )

        with open(digest_path, "w") as f:
            f.write(digest)
        
        logger.info(f"Ingested {len(documents)} documents into vector store")
    
    def retrieve(self, query: str, n_results: int = 10, 
                 filter_metadata: Dict[str, str] = None) -> List[Dict[str, Any]]:
        """Retrieve relevant documents"""
        if self.collection is None:
            logger.warning("No collection available for retrieval; attempting reload.")
            try:
                self.collection = self.client.get_collection(
                    name=self.collection_name,
                    embedding_function=self.embedding_fn
                )
            except Exception:
                return []
        
        where_filter = filter_metadata if filter_metadata else None
        
        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=n_results,
                where=where_filter
            )
        except Exception as e:
            # Handle missing collection or other query errors gracefully
            logger.warning(f"Vector query failed: {e}")
            try:
                self.collection = self.client.get_collection(
                    name=self.collection_name,
                    embedding_function=self.embedding_fn
                )
                results = self.collection.query(
                    query_texts=[query],
                    n_results=n_results,
                    where=where_filter
                )
            except Exception as e2:
                logger.error(f"Vector query retry failed: {e2}")
                return []
        
        # Format results
        retrieved_docs = []
        if results['documents'] and results['documents'][0]:
            for i, (content, metadata, doc_id, distance) in enumerate(zip(
                results['documents'][0],
                results['metadatas'][0],
                results['ids'][0],
                results['distances'][0]
            )):
                retrieved_docs.append({
                    'content': content,
                    'metadata': metadata,
                    'doc_id': doc_id,
                    'similarity_score': 1 - distance,  # Convert distance to similarity
                    'rank': i + 1
                })
        
        return retrieved_docs

    def _compute_digest(self, documents: List[Document]) -> str:
        data = []
        for d in documents:
            data.append({
                "id": d.doc_id,
                "meta": d.metadata,
                "content": d.content
            })
        blob = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.md5(blob).hexdigest()

def initialize_vectorstore() -> VectorStore:
    """Initialize and populate the vector store"""
    logger.info("Initializing vector store...")
    
    # Create ingester and load documents
    ingester = DocumentIngester(
        export_dir=config.superset_export_dir,
        context_file_path=config.context_file_path
    )
    
    documents = ingester.ingest_all()
    logger.info(f"Created {len(documents)} documents for ingestion")

    # Add dbt model documents for retrieval
    try:
        dbt_helper = DbtHelper(config.dbt_manifest_path, config.dbt_catalog_path)
        dbt_docs = _build_dbt_documents(dbt_helper)
        documents.extend(dbt_docs)
        logger.info(f"Added {len(dbt_docs)} dbt model documents for ingestion")
    except Exception as e:
        logger.warning(f"Skipping dbt model ingestion: {e}")
    
    # Create and populate vector store
    vectorstore = VectorStore()
    vectorstore.ingest_documents(documents)
    
    return vectorstore

def _build_dbt_documents(dbt_helper: DbtHelper) -> List[Document]:
    docs: List[Document] = []
    for model in dbt_helper.models.values():
        cols = []
        for c in (model.columns or [])[:30]:
            col_desc = c.description or ""
            cols.append(f"{c.name} ({c.type}) {col_desc}".strip())

        lineage = dbt_helper.get_lineage(model.name)
        content_parts = [
            f"DBT Model: {model.name}",
            f"Schema: {model.schema}",
            f"Database: {model.database}",
            f"Description: {model.description or ''}",
            f"Columns: {', '.join(cols)}",
            f"Upstream: {', '.join(lineage.get('upstream', []))}",
            f"Downstream: {', '.join(lineage.get('downstream', []))}",
        ]

        docs.append(Document(
            content="\n".join(content_parts),
            metadata={
                "type": "dbt_model",
                "model": model.name,
                "schema": model.schema,
                "table_name": model.name,
                "database": model.database,
            },
            doc_id=f"dbt_model_{model.schema}.{model.name}"
        ))

    return docs
