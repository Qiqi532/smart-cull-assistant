# -*- coding: utf-8 -*-
"""
similarity.py —— pHash 相似、连拍分组、并查集聚类

算法（设计文档 4.4.1 / 4.4.2）：
    1. 连拍分组：按 EXIF 时间戳排序，相邻间隔 < 1500ms（可配置）归入同一连拍组。
       无 EXIF 时回退为文件名相邻 + pHash 距离判组（ts 缺失时用文件顺序近似）。
    2. pHash：64 位感知哈希（imagehash.phash），汉明距离 < 12（可配置）视为相似。
    3. 并查集：把「同连拍组」或「pHash 相似」的照片合并为同一相似组，
       同时覆盖连拍组与跨机位相似组。

独立命令行调试：python -m engine.similarity <目录> [--limit N]
"""
from __future__ import annotations

import os

import numpy as np

from . import config, loader
from .loader import load_image
from .log import get_logger

try:
    import imagehash
except Exception:  # pragma: no cover
    imagehash = None

_log = get_logger("similarity")

# 阈值统一来自 engine/config.py
BURST_INTERVAL_MS = config.BURST_INTERVAL_MS     # 连拍时间间隔阈值
PHASH_THRESHOLD = config.PHASH_THRESHOLD         # pHash 汉明距离阈值
PHASH_HASH_SIZE = config.PHASH_HASH_SIZE         # 64 位 phash


class UnionFind:
    """并查集：用于把相似/连拍关系合并成组。"""

    def __init__(self, n: int):
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        # 路径压缩
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1

    def roots(self) -> dict[int, list[int]]:
        """返回 {root: [成员索引...]}，root 按组内最小索引升序。"""
        groups: dict[int, list[int]] = {}
        for i in range(len(self.parent)):
            r = self.find(i)
            groups.setdefault(r, []).append(i)
        order = sorted(groups.keys(), key=lambda r: min(groups[r]))
        return {r: groups[r] for r in order}


# ---------------------------------------------------------------------------
# pHash
# ---------------------------------------------------------------------------
def phash_of_image(img) -> str | None:
    """计算 64 位 pHash，返回十六进制字符串；失败返回 None。"""
    if imagehash is None or img is None:
        return None
    try:
        return str(imagehash.phash(img, hash_size=PHASH_HASH_SIZE))
    except Exception:
        return None


def _hamming_hex(a: str, b: str) -> int:
    if not a or not b:
        return 255
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def _hamming_matrix(hexes: list[str]) -> np.ndarray:
    """向量化计算两两汉明距离矩阵（分块控制内存）。"""
    n = len(hexes)
    mat = np.zeros((n, n), dtype=np.uint8)
    if n == 0:
        return mat
    vals = np.array([int(h, 16) if h else 0 for h in hexes], dtype=np.uint64)
    chunk = 128
    for i0 in range(0, n, chunk):
        i1 = min(i0 + chunk, n)
        xor = vals[i0:i1][:, None] ^ vals[None, :]          # (chunk, n) uint64
        # uint64 = 8 字节 = 64 位；unpackbits 展开为 (chunk, n*64)，再还原成 (chunk, n, 64)
        bits = np.unpackbits(xor.view(np.uint8), axis=1)
        mat[i0:i1] = bits.reshape(xor.shape[0], n, 64).sum(axis=2)
    return mat


# ---------------------------------------------------------------------------
# 相似聚类主函数
# ---------------------------------------------------------------------------
def group_similar(paths: list[str], ts_list: list[float],
                  burst_interval_ms: float = BURST_INTERVAL_MS,
                  phash_threshold: int = PHASH_THRESHOLD,
                  progress_cb=None,
                  phash_hexes: list[str] | None = None) -> tuple[list[str], list[int], list[list[str]]]:
    """相似聚类主函数。

    参数：
        paths              图像绝对路径列表（与 ts_list 等长）
        ts_list            每张的拍摄时间戳（毫秒），可为 None
        burst_interval_ms  连拍间隔阈值
        phash_threshold    pHash 汉明距离阈值
        progress_cb        optional 回调(已处理数, 总数)
        phash_hexes        optional 预计算的 phash 十六进制列表（与 paths 等长；
                           由调用方传入可避免重复解码原图——增量/断点续跑场景关键优化）

    返回：
        (phash_hexes, group_ids, groups)
        phash_hexes  每张的 phash 十六进制（可为 ''）
        group_ids    每张所属相似组编号（0 起）
        groups       [[路径...], ...] 按组序
    """
    n = len(paths)
    if phash_hexes is None:
        phash_hexes = []
        for i, p in enumerate(paths):
            if progress_cb:
                progress_cb(i + 1, n)
            img = load_image(p, max_size=config.PHASH_SIZE)
            phash_hexes.append(phash_of_image(img) or "")

    uf = UnionFind(n)

    # ---- 1) 连拍分组（时间戳）----
    valid_ts = [t for t in ts_list if t is not None]
    if valid_ts:
        order = sorted(range(n), key=lambda i: (ts_list[i] if ts_list[i] is not None else 1e18))
        for k in range(len(order) - 1):
            a, b = order[k], order[k + 1]
            ta, tb = ts_list[a], ts_list[b]
            if ta is not None and tb is not None and 0 <= (tb - ta) < burst_interval_ms:
                uf.union(a, b)

    # ---- 2) pHash 相似（汉明距离 < 阈值）----
    valid_idx = [i for i, h in enumerate(phash_hexes) if h]
    m = len(valid_idx)
    if m >= 2:
        # 只对有效哈希子集计算两两距离
        sub = [phash_hexes[i] for i in valid_idx]
        mat = _hamming_matrix(sub)
        # 上三角遍历合并
        rows, cols = np.triu_indices(m, k=1)
        for r, c in zip(rows, cols):
            if mat[r, c] < phash_threshold:
                uf.union(valid_idx[r], valid_idx[c])

    # ---- 3) 整理组 ----
    roots = uf.roots()
    group_ids = [0] * n
    groups: list[list[str]] = []
    for gid, members in enumerate(roots.values()):
        for idx in members:
            group_ids[idx] = gid
        groups.append([paths[idx] for idx in members])
    return phash_hexes, group_ids, groups


# ---------------------------------------------------------------------------
# 命令行调试入口
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    import time

    root = sys.argv[1] if len(sys.argv) > 1 else "."
    paths = loader.scan_directory(root)
    ts_list = [loader.read_exif(p)["ts"] for p in paths]
    t0 = time.time()
    hexes, gids, groups = group_similar(paths, ts_list)
    print(f"共 {len(paths)} 张 -> 相似组 {len(groups)} 个（耗时 {time.time() - t0:.1f}s）")
    for gi, g in enumerate(groups):
        if len(g) > 1:
            print(f"  组{gi}: {len(g)} 张 -> {[os.path.basename(x) for x in g]}")
