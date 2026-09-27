from __future__ import annotations

from app.services.bm25 import BM25Index, tokenize
from app.services.vector_store import _rrf_fuse


def test_tokenize_mixes_english_words_and_cjk_bigrams():
    tokens = tokenize("FastAPI 向量检索 vector")
    assert "fastapi" in tokens
    assert "vector" in tokens
    assert "向量" in tokens
    assert "量检" in tokens


def test_bm25_ranks_the_matching_document_first():
    documents = [
        "FastAPI 提供 Swagger UI 和 ReDoc 两个交互式 API 文档界面。",
        "线性回归通过最小化误差来拟合数据，属于监督学习。",
        "朴素贝叶斯假设特征之间条件独立。",
    ]
    index = BM25Index(documents)
    assert index.ranking("交互式 API 文档界面")[0] == 0
    assert index.ranking("条件独立 朴素贝叶斯")[0] == 2


def test_bm25_scores_are_zero_without_token_overlap():
    index = BM25Index(["机器学习", "深度学习"])
    assert index.scores("红烧肉") == [0.0, 0.0]


def test_rrf_fusion_rewards_agreement_between_retrievers():
    dense = [0, 1, 2, 3, 4]
    sparse = [2, 0, 1, 4, 3]
    fused = _rrf_fuse([dense, sparse])
    # Document 0 leads the dense list and is second in the sparse list, so it
    # outranks document 2, which only the sparse retriever ranks first.
    assert fused[0] == 0
    assert fused.index(2) < fused.index(3)
