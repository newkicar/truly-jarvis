"""增量 RAG 语义增强（src/rag.py）。

在 WIKI 导航式（grep + wikilink/backlink，src/wiki.py）基础上补充语义召回：
- 索引目录 `memory/rag-index/`（项目目录，不污染 vault）；持久化于 chromadb。
- **增量**：`{文件路径 → 内容 hash}` 缓存 JSON，仅对变更/新增文件重新 embedding
  （设计文档 §5.1「文件 hash 增量索引，只重建变更文件」）；删除文件同步移除。
- embedding 走 Ollama 本地模型 `bge-small-zh-v1.5`（512 维，中文本地离线），
  HTTP 调用 `POST /api/embed`（httpx，不引入新依赖）。
- 暴露 `vault_semantic_search` 工具：语义相近笔记 + 摘要片段，供 researcher
  与 grep/wiki 结果合并去重。

Ollama 未运行或模型缺失时：检索返回空并提示（不抛错，回落 grep/wiki）。
"""
import hashlib
import json
from pathlib import Path

import httpx

OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_EMBED_MODEL = "quentinz/bge-small-zh-v1.5"
INDEX_NAME = "vault_notes"
HASH_CACHE_FILE = "hashes.json"

# bge-small-zh 上下文 512 token；中文约按 1.5 字/token 保守切块，留安全余量
_CHUNK_CHARS = 700


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _embed_texts(texts: list[str], base_url: str = OLLAMA_BASE_URL) -> list[list[float]]:
    """调用 Ollama /api/embed 批量 embedding。"""
    resp = httpx.post(
        f"{base_url.rstrip('/')}/api/embed",
        json={"model": OLLAMA_EMBED_MODEL, "input": texts},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["embeddings"]


def _chunk_note(text: str) -> list[str]:
    """长笔记按字符切块（每块约 _CHUNK_CHARS 字符），保持可读边界。"""
    text = text.strip()
    if len(text) <= _CHUNK_CHARS:
        return [text] if text else []
    chunks = []
    for i in range(0, len(text), _CHUNK_CHARS):
        chunks.append(text[i : i + _CHUNK_CHARS])
    return chunks


def _hash_for_chunks(chunks: list[str]) -> str:
    """块级 hash：内容 hash 基础上再含块切分信息（同内容不同切分也触发重建）。"""
    return _content_hash("|".join(chunks))


class RagIndex:
    """增量向量索引：管理 chromadb 持久化 + 内容 hash 缓存。"""

    def __init__(self, rag_dir: Path, vault_root: Path, base_url: str = OLLAMA_BASE_URL):
        self.rag_dir = Path(rag_dir)
        self.rag_dir.mkdir(parents=True, exist_ok=True)
        self.vault_root = Path(vault_root)
        self.base_url = base_url
        self._hash_cache = self._load_hashes()

        import chromadb
        from chromadb.config import Settings

        self._client = chromadb.PersistentClient(
            path=str(self.rag_dir), settings=Settings(anonymized_telemetry=False)
        )
        self.collection = self._client.get_or_create_collection(
            INDEX_NAME, metadata={"hnsw:space": "cosine"}
        )

    # ---- 持久化 hash 缓存 ----
    def _hash_cache_path(self) -> Path:
        return self.rag_dir / HASH_CACHE_FILE

    def _load_hashes(self) -> dict[str, str]:
        p = self._hash_cache_path()
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_hashes(self) -> None:
        self._hash_cache_path().write_text(
            json.dumps(self._hash_cache, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    # ---- 增量构建 ----
    def refresh(self) -> dict:
        """扫描 vault，只对变更/新增笔记重新 embedding；移除已删除笔记。返回统计。"""
        notes = sorted(p for p in self.vault_root.rglob("*.md"))
        current_paths = {p.resolve().as_posix(): p for p in notes}
        old_paths = set(self._hash_cache)

        stats = {"added": 0, "updated": 0, "unchanged": 0, "removed": 0}

        # 移除已删除
        for key in old_paths - set(current_paths):
            self._delete_ids_by_path(key)
            self._hash_cache.pop(key, None)
            stats["removed"] += 1

        # 增量 embedding 变更文件
        to_embed = []
        new_hashes = {}
        for key, p in current_paths.items():
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            chunks = _chunk_note(text)
            h = _hash_for_chunks(chunks)
            new_hashes[key] = h
            if self._hash_cache.get(key) == h:
                stats["unchanged"] += 1
                continue
            if key in self._hash_cache:
                stats["updated"] += 1
            else:
                stats["added"] += 1
            to_embed.append((key, chunks))

        if to_embed:
            self._embed_and_upsert(to_embed)
        self._hash_cache = new_hashes
        self._save_hashes()
        return stats

    def _embed_and_upsert(self, items: list[tuple[str, list[str]]]) -> None:
        """分批 embedding 并 upsert 到 chromadb（id = 文件路径 + 块索引）。"""
        all_ids, all_embs, all_docs, all_metas = [], [], [], []
        for key, chunks in items:
            for i, chunk in enumerate(chunks):
                all_ids.append(f"{key}#{i}")
                all_docs.append(chunk)
                all_metas.append({"path": key, "chunk": i})
        # 分批（每批 32），避免单次请求过大
        batch = 32
        for start in range(0, len(all_ids), batch):
            slice_ids = all_ids[start : start + batch]
            slice_docs = all_docs[start : start + batch]
            embs = _embed_texts(slice_docs, self.base_url)
            self.collection.upsert(
                ids=slice_ids,
                embeddings=embs,
                documents=slice_docs,
                metadatas=all_metas[start : start + batch],
            )

    def _delete_ids_by_path(self, path_key: str) -> None:
        try:
            res = self.collection.get(where={"path": path_key})
            if res["ids"]:
                self.collection.delete(ids=res["ids"])
        except Exception:
            pass  # 索引无该文件或 collection 异常，忽略

    # ---- 检索 ----
    def search(self, query: str, k: int = 5, include_chunk: bool = True) -> list[dict]:
        """语义检索：返回 [{path, chunk, snippet, distance}]，按距离升序。

        Ollama 不可用时返回空列表（调用方回落 grep/wiki）。
        """
        if not query.strip():
            return []
        try:
            [emb] = _embed_texts([query], self.base_url)
        except (httpx.HTTPError, KeyError, IndexError):
            return []
        if self.collection.count() == 0:
            return []
        res = self.collection.query(
            query_embeddings=[emb], n_results=max(1, min(k, self.collection.count()))
        )
        out = []
        ids = res.get("ids", [[]])[0]
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        dists = res.get("distances", [[]])[0]
        for i in range(len(ids)):
            meta = metas[i] or {}
            chunk_text = docs[i] or ""
            out.append(
                {
                    "path": meta.get("path", "?"),
                    "chunk": meta.get("chunk", 0),
                    "snippet": chunk_text[:300],
                    "distance": round(dists[i], 4) if i < len(dists) else None,
                }
            )
        return out


def _vault_path(root: Path, abs_path: str) -> str:
    """绝对路径转 /vault/ 逻辑路径。"""
    try:
        rel = Path(abs_path).resolve().relative_to(Path(root).resolve())
        return "/vault/" + rel.as_posix()
    except ValueError:
        return abs_path


def make_semantic_search_tool(vault_root: Path, rag_dir: Path):
    """构造绑定 vault 的语义检索工具（langchain tool 形态）。"""
    root = Path(vault_root)

    def _search(query: str, k: int = 5) -> str:
        """语义检索知识库：返回与问题语义相近的笔记及摘要片段。

        与 grep（关键词）互补：grep 找得到精确词，本工具找得到「语义相关但用词不同」的笔记。
        结果含 /vault/ 路径，供 read_file 进一步读取。
        """
        index = RagIndex(rag_dir, root)
        try:
            stats = index.refresh()
        except Exception:
            stats = {}
        hits = index.search(query, k=k)
        if not hits:
            return (
                f"未找到语义相近笔记（索引 {index.collection.count()} 条，"
                f"本次增量 {stats.get('updated', 0)} 更新 + {stats.get('added', 0)} 新增）。"
                "可改用 grep 精确关键词检索。"
            )
        lines = [f"# 语义相近笔记（{len(hits)} 条）:"]
        for h in hits:
            lines.append(f"- {_vault_path(root, h['path'])}（距离 {h['distance']}）")
            if h["snippet"]:
                lines.append(f"  摘要: {h['snippet'].replace(chr(10), ' ')}")
        return "\n".join(lines)

    from langchain_core.tools import tool

    @tool
    def vault_semantic_search(query: str, k: int = 5) -> str:
        """语义检索知识库笔记（向量相似度，不是关键词）。查「语义相近但用词不同」的笔记。

        参数：query = 检索语义描述；k = 返回条数（默认 5）。
        结果含 /vault/ 路径，用 read_file 深入阅读；检索前自动增量更新索引。
        """
        return _search(query, k)

    return vault_semantic_search