# -*- coding: utf-8 -*-
"""
pipeline.py —— 端到端分析流水线（扫描→逐张指标→聚类→评分→入库）【MVP 版】

流程（设计文档 4.3 / 5）：
    1. 扫描目录（JPEG/PNG 默认，RAW 可选）
    2. 阶段一（流式、内存友好）：逐张解码 → 质量（模糊/曝光/BRISQUE）→ pHash
       → 人脸/闭眼(EAR)，结果【逐张写库】，线程池并行纯 cv2 部分
    3. 阶段二（CLIP 批量，一次前向）：美学 + 场景，结果逐批回写
    4. 相似聚类（时间戳连拍 + pHash 并查集）
    5. 组内场景自适应评分、废片判定、最佳帧推荐 / 不确定候选甄选 → 全量入库

MVP 新增能力：
    - 内存控制：不再一次性缓存全部原图，逐张/分批处理，5000+ 张不爆内存；
    - 断点续跑：阶段一/二结果实时落库，中断（含断电/异常）后重启只补算缺失部分；
    - 增量分析：mtime 未变化的照片跳过重算（复用已有指标）；
    - 并行化：模糊/曝光/哈希等无状态计算用线程池；CLIP 批量前向；
    - 分阶段计时：返回 phase_timing，供 scripts/benchmark.py 分段耗时统计。

独立命令行调试：python -m engine.pipeline <目录> [--db 路径]
"""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np

from . import config, loader, quality, similarity, scorer
from .aesthetics import analyze_batch, aesthetic_model_name
from .log import get_logger
from .store import PhotoStore

try:
    from . import faces as _faces
except Exception:  # pragma: no cover
    _faces = None

_log = get_logger("pipeline")

ANALYZE_SIZE = config.ANALYZE_SIZE        # 质量/人脸分析尺寸
CLIP_BATCH = config.CLIP_BATCH            # CLIP 批量推理大小（GPU 友好）
CLIP_LOAD_SIZE = config.CLIP_LOAD_SIZE    # CLIP 重解码尺寸
QUALITY_WORKERS = config.QUALITY_WORKERS  # 质量检测线程池并行数


def _ai_model_signature() -> str:
    """AI 模型签名（美学 + 质量 + 闭眼）。任一模型升级 → 签名变化 → 全量重算。"""
    aes = aesthetic_model_name()
    q = quality.quality_model_name()
    eye = _faces.eye_model_name() if _faces is not None else "none"
    return f"aes={aes}|q={q}|eye={eye}"


def _eyes_closed_from_row(row: dict) -> bool:
    """从已存 DB 行重建融合闭眼判定（增量分析时不重算照片，需忠实还原当时结论）。

    判定 = EAR<阈值 或 闭眼分类器概率>阈值（与 analyze 时 detect_face_and_eyes 一致）。
    """
    ear = row.get("eye_open")
    ep = row.get("eye_close_prob")
    if ear is not None and float(ear) < scorer.EAR_WASTE:
        return True
    if ep is not None and float(ep) > (_faces.EYE_MODEL_CONF if _faces is not None else config.EYE_MODEL_CONF):
        return True
    return False


def _stage1_worker(path: str) -> dict:
    """线程池 worker：解码 + 质量 + pHash（纯 cv2/PIL，无共享模型，线程安全）。

    返回 dict：ok / rgb / pil / q(质量指标) / phash。
    """
    try:
        pil = loader.load_image(path, max_size=ANALYZE_SIZE)
        if pil is None:
            return {"ok": False, "path": path}
        rgb = np.asarray(pil, dtype=np.uint8)
        q = quality.analyze_image_array(rgb)
        ph = similarity.phash_of_image(pil) or ""
        return {"ok": True, "path": path, "rgb": rgb, "pil": pil, "q": q, "phash": ph}
    except Exception as e:
        _log.warning("阶段一处理失败 %s: %s", path, e)
        return {"ok": False, "path": path}


def analyze_directory(root: str, db_path: str,
                      include_raw: bool = False,
                      use_faces: bool = True,
                      progress_cb=None,
                      cancel_check=None,
                      scene_override: dict | None = None,
                      forced_scene: str | None = None,
                      weights: tuple | None = None,
                      burst_interval_ms: float | None = None,
                      phash_threshold: int | None = None,
                      score_gap: float | None = None,
                      scene_conf_low: float | None = None) -> dict:
    """对目录执行完整分析并入库。

    参数：
        root            待分析目录
        db_path         SQLite 路径
        include_raw     是否包含 RAW
        use_faces       是否做人脸/闭眼检测（人像功能依赖）
        progress_cb     optional 回调(阶段名, 完成数, 总数)
        cancel_check    optional 返回 True 时中止
        scene_override  optional {path: scene} 人工修正的场景覆盖
        forced_scene    可选，强制整批按指定场景（人像/风光/其他）
        weights         可选，自定义综合分权重 (w0,w1,w2,w3)，覆盖场景预设
        burst_interval_ms 可选，连拍间隔阈值覆盖（默认 config）
        phash_threshold 可选，pHash 距离阈值覆盖（默认 config）
        score_gap       可选，Top1-Top2 分差阈值覆盖（默认 config）
        scene_conf_low  可选，场景置信度阈值覆盖（默认 config）
    返回：
        汇总 dict（total, new_analyzed, groups, wastes, bests, uncertain_groups,
        phase_timing 等）
    """
    t_start = time.time()
    phase_t = {}       # 分阶段耗时（秒），供 benchmark

    def _phase_start(name):
        phase_t[name] = time.time()

    def _phase_end(name):
        if name in phase_t:
            phase_t[name] = time.time() - phase_t[name]

    def report(phase: str, done: int, total: int):
        if progress_cb:
            progress_cb(phase, done, total)

    # 阈值覆盖（默认取 config，界面滑块修改即生效）
    burst_interval_ms = burst_interval_ms if burst_interval_ms is not None else config.BURST_INTERVAL_MS
    phash_threshold = phash_threshold if phash_threshold is not None else config.PHASH_THRESHOLD
    score_gap = score_gap if score_gap is not None else config.SCORE_GAP
    scene_conf_low = scene_conf_low if scene_conf_low is not None else config.SCENE_CONF_LOW

    # ---- 1) 扫描 ----
    _phase_start("扫描")
    report("扫描", 0, 1)
    root_abs = os.path.abspath(root)
    paths = loader.scan_directory(root, include_raw=include_raw)
    n = len(paths)
    if n == 0:
        report("扫描", 1, 1)
        _phase_end("扫描")
        return {"total": 0, "message": "目录中没有找到支持的图片（JPEG/PNG）", "phase_timing": phase_t}
    _phase_end("扫描")

    # ---- 2) 读取元数据 + 增量/断点判断 ----
    _phase_start("读取元数据")
    report("读取元数据", 0, n)
    with PhotoStore(db_path) as store:
        # 切换分析源：若上次分析的目录与本次不同，重置旧库（避免跨源混杂/重复行）
        prev_root = store.get_meta("source_root")
        if prev_root and prev_root != root_abs:
            store.clear_all()
        # AI 模型升级失效：任一模型版本变化 → 旧库整体重算
        prev_sig = store.get_meta("ai_models")
        cur_sig = _ai_model_signature()
        if prev_sig and prev_sig != cur_sig:
            store.clear_all()
        elif prev_sig is None and store.count_photos() > 0:
            store.clear_all()
        meta = []       # 每张：{path, fname, ts, mtime, width, height}
        # 性能关键：一次性读回旧库，避免 1000+ 次逐行查询
        old_map = store.photos_map()
        need_stage1 = []    # 需要阶段一（新文件 / mtime 变化 / 断点缺失）
        need_clip = set()   # 需要 CLIP（新分析 / 断点缺失 aesthetic）
        for i, p in enumerate(paths):
            if cancel_check and cancel_check():
                return {"total": n, "message": "已取消", "cancelled": True, "phase_timing": phase_t}
            ex = loader.read_exif(p)
            mt = loader.get_mtime(p)
            meta.append({"path": p, "fname": os.path.basename(p), "ts": ex["ts"],
                         "mtime": mt, "width": ex["width"], "height": ex["height"]})
            old = old_map.get(p)
            mtime_ok = old and abs((old.get("mtime") or 0) - mt) < 1e-6
            # 增量 + 断点：mtime 一致且阶段一字段齐全 → 跳过阶段一
            stage1_ok = mtime_ok and old.get("blur_score") is not None and old.get("phash")
            if not stage1_ok:
                need_stage1.append(i)
            # CLIP：本批次新分析的，或断点时缺 aesthetic 的
            if not stage1_ok:
                need_clip.add(i)
            elif old and (old.get("aesthetic") is None or old.get("scene") is None):
                need_clip.add(i)
            if progress_cb:
                progress_cb("读取元数据", i + 1, n)
        _phase_end("读取元数据")

        # ---- 3) 阶段一：质量/BRISQUE/人脸/phash（流式 + 线程池）----
        n_new = len(need_stage1)
        stage1 = {}      # idx -> 阶段一指标 dict
        if n_new > 0:
            _phase_start("质量与哈希")
            report("质量与哈希", 0, n_new)
            done = 0
            with ThreadPoolExecutor(max_workers=QUALITY_WORKERS) as ex:
                futs = {ex.submit(_stage1_worker, meta[idx]["path"]): idx for idx in need_stage1}
                for fut in as_completed(futs):
                    if cancel_check and cancel_check():
                        # 取消：放弃未完成结果，已完成的已逐张落库
                        for f in futs:
                            f.cancel()
                        _phase_end("质量与哈希")
                        return {"total": n, "message": "已取消", "cancelled": True,
                                "new_analyzed": done, "phase_timing": phase_t}
                    idx = futs[fut]
                    r = fut.result()
                    if not r.get("ok"):
                        stage1[idx] = {"ok": False}
                    else:
                        rgb, pil, q = r["rgb"], r["pil"], r["q"]
                        # 以下两步在主线程串行（共享 torch/pyiqa 与 MediaPipe 实例，避免并发）
                        brisque = quality.brisque_score_array(rgb)
                        face = {"is_face": False, "ear": None, "eyes_closed": False,
                                "eye_close_prob": None}
                        if use_faces and _faces is not None:
                            try:
                                fr = _faces.detect_face_and_eyes(rgb, pil)
                                face = {"is_face": fr["is_face"], "ear": fr["ear"],
                                        "eyes_closed": fr["eyes_closed"],
                                        "eye_close_prob": fr["eye_close_prob"]}
                            except Exception as e:
                                _log.warning("人脸检测异常 %s: %s", meta[idx]["path"], e)
                        stage1[idx] = {
                            "ok": True, "blur_score": q["blur_score"],
                            "over": q["over"], "under": q["under"], "brisque": brisque,
                            "is_face": face["is_face"], "ear": face["ear"],
                            "eyes_closed": face["eyes_closed"],
                            "eye_close_prob": face["eye_close_prob"],
                            "phash": r["phash"],
                        }
                        # 【断点续跑】阶段一结果立即写库（WAL 单事务，断电/异常不丢已算部分）
                        _write_stage1(store, meta[idx], stage1[idx])
                    done += 1
                    report("质量与哈希", done, n_new)
            _phase_end("质量与哈希")

        # ---- 4) 阶段二：CLIP 批量（美学 + 场景，一次前向，GPU 优先）----
        _phase_start("美学与场景")
        order = sorted(need_clip)
        clip_res = {}
        if order:
            report("美学与场景", 0, len(order))
            for b in range(0, len(order), CLIP_BATCH):
                if cancel_check and cancel_check():
                    _phase_end("美学与场景")
                    return {"total": n, "message": "已取消", "cancelled": True,
                            "new_analyzed": n_new, "phase_timing": phase_t}
                batch_idx = order[b:b + CLIP_BATCH]
                batch_imgs, valid = [], []
                for i in batch_idx:
                    im = loader.load_image(meta[i]["path"], max_size=CLIP_LOAD_SIZE)
                    if im is not None:
                        batch_imgs.append(im)
                        valid.append(i)
                if valid:
                    res = analyze_batch(batch_imgs)
                    for i, r in zip(valid, res):
                        clip_res[i] = r
                        # 【断点续跑】逐张回写美学/场景
                        store.update_photo(meta[i]["path"],
                                           aesthetic=r["aesthetic"],
                                           scene=r["scene"],
                                           scene_conf=r["scene_conf"])
                if progress_cb:
                    progress_cb("美学与场景", min(b + CLIP_BATCH, len(order)), len(order))
        _phase_end("美学与场景")

        # ---- 5) pHash 汇总（复用 stage1 / 已存库，避免重新解码原图）----
        _phase_start("相似聚类")
        report("相似聚类", 0, n)
        phash_hexes = []
        ts_list = []
        for i, m in enumerate(meta):
            if i in stage1 and stage1[i].get("ok"):
                h = stage1[i]["phash"]
            else:
                old = old_map.get(m["path"])
                h = (old or {}).get("phash") or ""
            phash_hexes.append(h)
            ts_list.append(m["ts"])

        # 聚类（传入预计算 phash，避免增量/断点时重复解码）
        hexes, group_ids, groups = similarity.group_similar(
            [m["path"] for m in meta], ts_list,
            burst_interval_ms=burst_interval_ms, phash_threshold=phash_threshold,
            progress_cb=lambda done, total: report("相似聚类", done, total),
            phash_hexes=phash_hexes)
        _phase_end("相似聚类")

        # ---- 6) 场景覆盖（人工修正 / 强制场景）----
        scene_override = scene_override or {}

        def resolve_scene(idx):
            p = meta[idx]["path"]
            # 1) 参数传入的人工修正（本次会话）
            if p in scene_override:
                return scene_override[p], 1.0
            # 2) 强制整批场景
            if forced_scene:
                return forced_scene, 1.0
            # 3) DB 中人工修正的场景（场景手动修正入口，跨会话持久）
            old_row = old_map.get(p)
            if old_row and old_row.get("scene_manual"):
                return old_row["scene_manual"], 1.0
            # 4) 本次 CLIP 结果
            if idx in clip_res:
                return clip_res[idx]["scene"], clip_res[idx]["scene_conf"]
            # 5) 复用已存自动场景
            if old_row and old_row.get("scene"):
                return old_row["scene"], old_row.get("scene_conf") or 1.0
            return "其他", 1.0

        def resolve_aesthetic(idx):
            if idx in clip_res:
                return clip_res[idx]["aesthetic"]
            old = old_map.get(meta[idx]["path"])
            if old and old.get("aesthetic") is not None:
                return old["aesthetic"]
            return 50.0

        # ---- 7) 组内评分、废片判定、最佳帧/不确定甄选 ----
        _phase_start("评分与甄选")
        report("评分与甄选", 0, len(groups))
        n_best = 0
        n_uncertain_groups = 0
        n_candidate_photos = 0
        waste_count = 0
        for gi, group in enumerate(groups):
            if cancel_check and cancel_check():
                _phase_end("评分与甄选")
                return {"total": n, "message": "已取消", "cancelled": True,
                        "new_analyzed": n_new, "phase_timing": phase_t}
            # 组内索引
            idx_of_path = {meta[i]["path"]: i for i in range(n)}
            member_idx = [idx_of_path[p] for p in group]
            # 场景：取组内主要场景（人像/风光优先于其他）
            scene_counts = {}
            for i in member_idx:
                s, _ = resolve_scene(i)
                scene_counts[s] = scene_counts.get(s, 0) + 1
            if scene_counts.get("人像", 0) > 0:
                scene = "人像"
            elif scene_counts.get("风光", 0) > 0:
                scene = "风光"
            else:
                scene = "其他"
            # 组置信度：组内场景置信度均值
            confs = [resolve_scene(i)[1] for i in member_idx]
            group_conf = sum(confs) / len(confs) if confs else 1.0

            # 计算每张的综合分（废片原因在判定后基于 dup_paths 再算）
            scored = []
            for i in member_idx:
                p = meta[i]["path"]
                m = stage1.get(i)
                if m is None or not m.get("ok"):
                    old = old_map.get(p) or {}
                    m = {"ok": True,
                         "blur_score": old.get("blur_score") or 0.0,
                         "over": old.get("over_ratio") or 0.0,
                         "under": old.get("under_ratio") or 0.0,
                         "is_face": bool(old.get("is_face")),
                         "ear": old.get("eye_open"),
                         "brisque": old.get("brisque"),
                         "eyes_closed": _eyes_closed_from_row(old)}
                aes = resolve_aesthetic(i)
                s, conf = resolve_scene(i)
                photo_score = scorer.analyze_photo_score(
                    {**m, "aesthetic": aes}, scene, weights)
                hw = scorer.is_hard_waste(
                    scene, m["blur_score"], m["over"], m["under"],
                    bool(m.get("eyes_closed", False)), m.get("brisque"))
                scored.append({**photo_score, "path": p, "hard_waste": hw})

            # 判定：best / uncertain（阈值可被界面滑块覆盖）
            verdict, picks = scorer.judge_and_pick(scored, scene, group_conf,
                                                   score_gap=score_gap,
                                                   scene_conf_low=scene_conf_low)
            best_path = picks[0]["path"] if picks else ""
            is_uncertain = (verdict == "uncertain")
            n_candidates = len(picks) if is_uncertain else 0
            if is_uncertain:
                n_uncertain_groups += 1
            elif picks:
                n_best += 1

            # “高度重复”去重废片语义（见上一版注释）
            dup_paths: set[str] = set()
            if not is_uncertain and len(scored) > 2:
                scored_sorted = sorted(scored, key=lambda x: -x["comp_score"])
                dup_paths = {x["path"] for x in scored_sorted[2:]}

            # 组内每张入库（批量事务写入）
            rows = []
            for i in member_idx:
                p = meta[i]["path"]
                m = stage1.get(i, {})
                old = old_map.get(p) or {}
                ph = hexes[i]
                ps = next((x for x in scored if x["path"] == p), None)
                comp = ps["comp_score"] if ps else 0.0
                dup = p in dup_paths
                m_ok = bool(m.get("ok"))
                reasons = scorer.waste_reasons(
                    scene,
                    (m.get("blur_score") if m_ok else (old.get("blur_score") or 0.0)),
                    (m.get("over") if m_ok else (old.get("over_ratio") or 0.0)),
                    (m.get("under") if m_ok else (old.get("under_ratio") or 0.0)),
                    (bool(m.get("eyes_closed", False)) if m_ok else _eyes_closed_from_row(old)),
                    dup,
                    (m.get("brisque") if m_ok else old.get("brisque")))
                s, conf = resolve_scene(i)
                aes = resolve_aesthetic(i)
                is_cand = is_uncertain and p in [x["path"] for x in picks]
                rank = ([x["path"] for x in picks].index(p) + 1) if is_cand else 0
                is_best = (not is_uncertain and p == best_path)
                row = {
                    "path": p,
                    "fname": meta[i]["fname"],
                    "ts": meta[i]["ts"],
                    "mtime": meta[i]["mtime"],
                    "width": meta[i]["width"],
                    "height": meta[i]["height"],
                    "scene": s, "scene_conf": conf,
                    "blur_score": (m.get("blur_score") if m.get("ok") else (old.get("blur_score") or 0.0)),
                    "over_ratio": (m.get("over") if m.get("ok") else (old.get("over_ratio") or 0.0)),
                    "under_ratio": (m.get("under") if m.get("ok") else (old.get("under_ratio") or 0.0)),
                    "aesthetic": aes,
                    "eye_open": (m.get("ear") if m_ok else old.get("eye_open")),
                    "is_face": int(m.get("is_face", False) if m_ok else bool(old.get("is_face"))),
                    "brisque": (m.get("brisque") if m_ok else old.get("brisque")),
                    "eye_close_prob": (m.get("eye_close_prob") if m_ok else old.get("eye_close_prob")),
                    "phash": ph,
                    "group_id": gi,
                    "comp_score": comp,
                    "is_waste": 1 if reasons else 0,
                    "is_best": 1 if is_best else 0,
                    "is_uncertain": 1 if is_uncertain else 0,
                    "is_candidate": 1 if is_cand else 0,
                    "candidate_rank": rank,
                    "waste_reasons": ",".join(reasons) if reasons else None,
                    "star": ((old.get("star") if old else 0) or 0)
                            or (5 if (is_best and not (old.get("star") if old else 0)) else 0),
                    "label": (old.get("label") if old else None),
                }
                rows.append(row)
                if reasons:
                    waste_count += 1
            store.upsert_photos_batch(rows)
            # 组记录
            store.set_group(gi, len(group), best_path, is_uncertain, n_candidates)
            if is_uncertain:
                n_candidate_photos += n_candidates
            if progress_cb:
                progress_cb("评分与甄选", gi + 1, len(groups))
        _phase_end("评分与甄选")

        # ---- 汇总 ----
        store.set_meta("source_root", root_abs)
        store.set_meta("ai_models", _ai_model_signature())
        st = store.stats()
        _log.info("分析完成：%s 张，新增 %s，耗时 %.1fs", n, n_new, time.time() - t_start)
        return {
            "total": n,
            "new_analyzed": n_new,
            "groups": len(groups),
            "best_groups": n_best,
            "uncertain_groups": n_uncertain_groups,
            "candidate_photos": n_candidate_photos,
            "waste": waste_count,
            "scene_dist": st.get("scenes", {}),
            "aesthetic_model": aesthetic_model_name(),
            "quality_model": quality.quality_model_name(),
            "eye_model": _faces.eye_model_name() if _faces is not None else "none",
            "elapsed": time.time() - t_start,
            "phase_timing": phase_t,
            "message": "分析完成",
        }


def _write_stage1(store: PhotoStore, m: dict, s1: dict):
    """把阶段一结果写库（断点续跑的最小落库单元）。"""
    if not s1.get("ok"):
        # 解码失败的照片也记录 mtime，避免每次重试（仍是 NULL 指标，重算可覆盖）
        store.upsert_photo({
            "path": m["path"], "fname": m["fname"], "ts": m["ts"], "mtime": m["mtime"],
            "width": m["width"], "height": m["height"],
        })
        return
    store.upsert_photo({
        "path": m["path"], "fname": m["fname"], "ts": m["ts"], "mtime": m["mtime"],
        "width": m["width"], "height": m["height"],
        "blur_score": s1["blur_score"], "over_ratio": s1["over"],
        "under_ratio": s1["under"], "brisque": s1["brisque"],
        "is_face": int(s1["is_face"]), "eye_open": s1["ear"],
        "eye_close_prob": s1["eye_close_prob"], "phash": s1["phash"],
    })


# ---------------------------------------------------------------------------
# 命令行调试入口
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    root = sys.argv[1] if len(sys.argv) > 1 else "data"
    db = sys.argv[2] if len(sys.argv) > 2 else "data/cull.db"
    print(f"分析目录: {root} -> DB: {db}")
    summary = analyze_directory(root, db)
    print("汇总：", summary)
