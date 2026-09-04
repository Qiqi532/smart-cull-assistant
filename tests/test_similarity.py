# -*- coding: utf-8 -*-
"""similarity.py 单测：连拍分组、pHash 相似、并查集聚类合并。

说明：group_similar 内部会调用 load_image(path) 然后 phash_of_image(img)。
这里把 load_image 伪装成返回 path 本身，再让 phash_of_image 按 path 返回
预置哈希，从而在不读真实图片的前提下覆盖纯聚类逻辑。
"""
from __future__ import annotations

from engine.similarity import UnionFind, _hamming_hex, group_similar

H0 = "0" * 16
H1 = "3000000000000000"   # 与 H0 汉明距离 2
H2 = "7000000000000000"   # 与 H1 距离 2、与 H0 距离 4
HF = "f" * 16             # 与 H0 距离 64
H55 = "5" * 16            # 与 H0/HF 各距离 32（互相远离）


def test_union_find_basic():
    uf = UnionFind(5)
    uf.union(0, 1)
    uf.union(3, 4)
    assert uf.find(0) == uf.find(1)
    assert uf.find(0) != uf.find(2)
    roots = uf.roots()
    assert len(roots) == 3  # {0,1} {2} {3,4}


def test_union_find_path_compression():
    uf = UnionFind(4)
    uf.union(0, 1)
    uf.union(2, 3)
    uf.union(1, 2)   # 合并两个组
    assert len(uf.roots()) == 1


def test_hamming_hex():
    assert _hamming_hex("0" * 16, "0" * 16) == 0
    # 翻转所有位 -> 64
    assert _hamming_hex("0" * 16, "f" * 16) == 64
    assert _hamming_hex("", "abc") == 255


def _setup(monkeypatch, phash_map):
    monkeypatch.setattr("engine.similarity.load_image", lambda p, **kw: p)
    monkeypatch.setattr("engine.similarity.phash_of_image", lambda img: phash_map[img])


def test_group_similar_burst_only(monkeypatch):
    """时间戳相邻（间隔 < 阈值）应聚为一组，且不触发 pHash 合并（哈希全不同）。"""
    paths = ["a.jpg", "b.jpg", "c.jpg"]
    ts = [0.0, 1000.0, 5000.0]   # a-b 连拍；c 独立
    _setup(monkeypatch, {"a.jpg": H0, "b.jpg": HF, "c.jpg": H55})
    _, gids, groups = group_similar(paths, ts)
    assert gids[0] == gids[1] != gids[2]
    assert len(groups) == 2


def test_group_similar_burst_threshold(monkeypatch):
    """间隔恰好等于阈值（1500ms）不算连拍。"""
    paths = ["a.jpg", "b.jpg"]
    ts = [0.0, 1500.0]
    _setup(monkeypatch, {"a.jpg": H0, "b.jpg": HF})
    _, gids, groups = group_similar(paths, ts)
    assert gids[0] != gids[1]
    assert len(groups) == 2


def test_group_similar_phash_merge(monkeypatch):
    """pHash 相近的跨时间照片应被并查集合并进同一组。"""
    paths = ["x.jpg", "y.jpg", "z.jpg"]
    ts = [1000.0, 200000.0, 300000.0]  # 时间相差很大，仅靠 pHash
    _setup(monkeypatch, {"x.jpg": H0, "y.jpg": H1, "z.jpg": HF})
    _, gids, groups = group_similar(paths, ts)
    assert gids[0] == gids[1] != gids[2]
    assert len(groups) == 2


def test_group_similar_chain_merge(monkeypatch):
    """A-B 连拍、B-C 相似 → 三者应合并为一组（传递合并）。"""
    paths = ["a.jpg", "b.jpg", "c.jpg"]
    ts = [0.0, 1000.0, 500000.0]     # a-b 连拍
    _setup(monkeypatch, {"a.jpg": H0, "b.jpg": H1, "c.jpg": H2})
    _, gids, groups = group_similar(paths, ts)
    assert gids[0] == gids[1] == gids[2]
    assert len(groups) == 1


def test_group_similar_no_ts_no_hash_single(monkeypatch):
    """无时间戳且无有效哈希时，每张独立成组。"""
    paths = ["a.jpg", "b.jpg"]
    ts = [None, None]
    monkeypatch.setattr("engine.similarity.load_image", lambda p, **kw: p)
    monkeypatch.setattr("engine.similarity.phash_of_image", lambda img: None)
    _, gids, groups = group_similar(paths, ts)
    assert gids[0] != gids[1]
    assert len(groups) == 2
