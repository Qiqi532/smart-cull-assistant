# -*- coding: utf-8 -*-
"""
app.py —— 光影选片助手（Smart Cull Assistant）Streamlit 入口（MVP 版）

四阶段向导式交互流（参考 Photo Mechanic / Aftershoot / Narrative Select / Lightroom）：
    ① 导入    —— 选择本地文件夹 或 上传照片
    ② 自动分析 —— 一键自动化（废片/相似组/场景/最佳帧/不确定组），带进度，完成后自动跳转
    ③ 人工复核 —— 大图横向对比（候选并排大图）+ 底部胶片条 + 键盘驱动拍板
                  + 总览排行榜（全局评分排序 / 星级 / 废片 / 场景过滤 / 场景手动修正）
    ④ 确认导出 —— 检查所有选中照片 → 导出 CSV / 复制保留文件

MVP 新增：
    - 侧栏“分析阈值”滑块与 engine/config.py 同源（改配置即生效、界面与引擎口径一致）；
    - 复核页新增「总览排行榜」：全局综合分排序、按星级/废片/场景/推荐过滤、
      多字段排序、场景手动修正入口（写库，跨会话生效、重分析不被覆盖）。
深色摄影主题见 .streamlit/config.toml。算法全部在 engine/，本文件只负责展示与交互。
"""
from __future__ import annotations

import base64
import csv
import os
import shutil
import sys
import time

import streamlit as st

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from engine import config, loader, scorer  # noqa: E402
from engine.pipeline import analyze_directory  # noqa: E402
from engine.store import PhotoStore  # noqa: E402

st.set_page_config(page_title="光影选片助手", page_icon="📷", layout="wide")

APP_TITLE = "📷 光影选片助手 Smart Cull Assistant"
DEFAULT_DB = config.DEFAULT_DB
UPLOAD_ROOT = os.path.join(config.DATA_DIR, "uploads")
DEMO_DIR = os.path.join(config.DATA_DIR, "demo")
STAGES = [("import", "① 导入"), ("analyzing", "② 自动分析"),
          ("review", "③ 人工复核"), ("confirm", "④ 确认导出")]
# 场景手动修正可选值：'自动' = 清除修正回到自动识别
SCENE_OPTIONS = ["自动", "人像", "风光", "建筑", "街拍", "宠物", "静物", "其他"]


# ---------------------------------------------------------------------------
# 会话状态
# ---------------------------------------------------------------------------
def init_state():
    s = st.session_state
    s.setdefault("page", "import")
    s.setdefault("source", "")
    s.setdefault("source_kind", "folder")     # folder | upload | demo
    s.setdefault("analyzing", False)
    s.setdefault("review_idx", 0)
    s.setdefault("undo_stack", [])
    s.setdefault("db_path", DEFAULT_DB)
    s.setdefault("analysis", None)
    s.setdefault("kb_seq", 0)
    # 侧栏阈值（默认取 config，界面与引擎同源）
    s.setdefault("p_burst", config.BURST_INTERVAL_MS)
    s.setdefault("p_phash", config.PHASH_THRESHOLD)
    s.setdefault("p_gap", config.SCORE_GAP)
    s.setdefault("p_conf", config.SCENE_CONF_LOW)


init_state()


def go(page: str):
    st.session_state["page"] = page
    st.rerun()


def inject_css():
    st.markdown("""<style>
    .block-container { padding-top: 1.1rem; padding-bottom: 1rem; }
    div[data-testid="stMetric"] {
        background: rgba(255,255,255,0.05); border-radius: 10px; padding: 8px 14px;
        border: 1px solid rgba(255,255,255,0.08);
    }
    .stButton > button { border-radius: 8px; font-weight: 500; }
    .step-done { color: #8BC8EA; }
    .step-cur  { color: #e8eaed; font-weight: 700; }
    .step-pending { color: #6B7280; }
    .kb-row { background: rgba(139,200,234,0.08); border: 1px solid rgba(139,200,234,0.2);
              border-radius: 8px; padding: 6px 10px; font-size: 12px; color: #9aa3af; }
    </style>""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 侧栏（阈值滑块 + 设备信息）
# ---------------------------------------------------------------------------
def sidebar():
    import torch
    with st.sidebar:
        st.markdown("### ⚙️ 参数")
        dev = "✅ GPU 推理" if torch.cuda.is_available() else "💻 CPU（自动降级）"
        st.caption(f"推理设备：{dev}")
        with st.expander("分析阈值（与引擎同源，改配置即生效）"):
            st.session_state["p_burst"] = st.slider(
                "连拍间隔 (ms)", 300, 5000, int(config.BURST_INTERVAL_MS), 100,
                help="EXIF 拍摄时间间隔小于该值视为同一连拍组")
            st.session_state["p_phash"] = st.slider(
                "pHash 相似距离", 4, 32, int(config.PHASH_THRESHOLD),
                help="pHash 汉明距离小于该值视为相似（64 位）")
            st.session_state["p_gap"] = st.slider(
                "甄选分差", 1.0, 10.0, float(config.SCORE_GAP), 0.5,
                help="组内 Top1-Top2 综合分差小于该值 → 进入待甄选")
            st.session_state["p_conf"] = st.slider(
                "场景置信阈值", 0.30, 0.95, float(config.SCENE_CONF_LOW), 0.05,
                help="场景置信度低于该值 → 进入待甄选 / 归为其他")
        st.divider()
        st.caption("默认权重：人像(0.25/0.20/0.25/0.30) · 风光(0.35/0.30/0.35/0.00) · "
                   "其他(0.30/0.20/0.30/0.20)，自动识别不靠人工调权重。")


# ---------------------------------------------------------------------------
# 顶部流程条
# ---------------------------------------------------------------------------
def stepper():
    cur = st.session_state.get("page", "import")
    order = [k for k, _ in STAGES]
    idx_cur = order.index(cur) if cur in order else 0
    cols = st.columns(len(STAGES))
    for i, (key, label) in enumerate(STAGES):
        with cols[i]:
            kwargs = {}
            if i == idx_cur:
                kwargs["type"] = "primary"
            if st.button(label, key=f"step_{key}", width="stretch", **kwargs):
                go(key)
    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 快捷键（聚焦输入框捕获）
# ---------------------------------------------------------------------------
def kb_widget(label="点击此框后使用快捷键"):
    box_key = f"kb_box_{st.session_state['kb_seq']}"
    k = st.text_input(label, key=box_key, label_visibility="collapsed",
                      placeholder=label, help="0-5 标星 | P 保留 | X 排除 | A/B/C/D 选候选 | Tab/→ 下一组 | ← 上一组 | Esc 退出")
    if k:
        handle_key(k.strip())
        st.session_state["kb_seq"] += 1
        st.rerun()
    return k


def handle_key(key: str):
    s = st.session_state
    if s.get("page") != "review":
        return
    if key in ("0", "1", "2", "3", "4", "5"):
        _star_current(int(key))
    elif key in ("p", "P"):
        _pick_current("P")
    elif key in ("x", "X"):
        _pick_current("X")
    elif key in ("a", "A"):
        _pick_candidate(0)
    elif key in ("b", "B"):
        _pick_candidate(1)
    elif key in ("c", "C"):
        _pick_candidate(2)
    elif key in ("d", "D"):
        _pick_candidate(3)
    elif key in ("Tab", "ArrowRight", "ArrowDown"):
        _next_review_group()
    elif key in ("ArrowLeft", "ArrowUp"):
        _prev_review_group()
    elif key == "Escape":
        st.session_state["review_idx"] = -1


# ---------------------------------------------------------------------------
# 数据操作（带撤销）
# ---------------------------------------------------------------------------
def _push(kind, path, old, new):
    st.session_state["undo_stack"].append((kind, path, old, new))


def _set_star(path: str, star: int):
    with PhotoStore(st.session_state["db_path"]) as s:
        old = (s.get_photo(path) or {}).get("star", 0)
        s.set_star(path, star)
    _push("star", path, old, star)


def _set_label(path: str, label: str):
    with PhotoStore(st.session_state["db_path"]) as s:
        old = (s.get_photo(path) or {}).get("label") or ""
        s.set_pick(path, label)
    _push("label", path, old, label)


def _set_scene(path: str, scene: str):
    """场景手动修正：'自动' 表示清除修正回到自动识别。"""
    with PhotoStore(st.session_state["db_path"]) as s:
        s.set_scene_manual(path, None if scene == "自动" else scene)
        if scene != "自动":
            s.update_photo(path, scene=scene, scene_conf=1.0)


def _undo():
    stack = st.session_state["undo_stack"]
    if not stack:
        return
    kind, path, old, new = stack.pop()
    with PhotoStore(st.session_state["db_path"]) as s:
        if kind == "star":
            s.set_star(path, old)
        elif kind == "label":
            s.set_label(path, old)
    st.rerun()


def _current_group() -> tuple:
    """当前待甄选组：(group_id, candidates)。"""
    with PhotoStore(st.session_state["db_path"]) as s:
        groups = s.uncertain_groups()
        if not groups:
            return None, []
        idx = st.session_state.get("review_idx", 0)
        if idx < 0:
            idx = 0
        idx = min(idx, len(groups) - 1)
        g = groups[idx]
        return g, s.candidates(g["id"])


def _star_current(star: int):
    _, cands = _current_group()
    if cands:
        _set_star(cands[0]["path"], star)


def _pick_current(label: str):
    _, cands = _current_group()
    if cands:
        _set_label(cands[0]["path"], label)
        _next_review_group()


def _pick_candidate(i: int):
    _, cands = _current_group()
    if i < len(cands):
        _set_star(cands[i]["path"], 5)
        _set_label(cands[i]["path"], "P")
    _next_review_group()


def _review_total() -> int:
    with PhotoStore(st.session_state["db_path"]) as s:
        return len(s.uncertain_groups())


def _next_review_group():
    n = _review_total()
    idx = st.session_state.get("review_idx", 0)
    if n == 0:
        return
    if idx < n - 1:
        st.session_state["review_idx"] = idx + 1
        st.rerun()
    else:
        st.session_state["review_idx"] = -1   # 全部完成
        st.rerun()


def _prev_review_group():
    idx = st.session_state.get("review_idx", 0)
    if idx > 0:
        st.session_state["review_idx"] = idx - 1
        st.rerun()


# ---------------------------------------------------------------------------
# 展示辅助
# ---------------------------------------------------------------------------
def thumb_of(path: str, size: int = 320) -> str | None:
    return loader.make_thumbnail(path, size=size)


def badge(p: dict) -> str:
    tags = []
    if p.get("star"):
        tags.append(f"★{p['star']}")
    if p.get("label") == "P":
        tags.append("P")
    elif p.get("label") == "X":
        tags.append("X")
    if p.get("is_best"):
        tags.append("推荐")
    if p.get("is_candidate"):
        tags.append("候选")
    if p.get("is_waste"):
        tags.append("废:" + (p.get("waste_reasons") or ""))
    return " ".join(tags) if tags else "—"


def _fs_color(p: dict) -> str:
    """胶片条状态边框色：废片红 / 最佳绿 / 保留金 / 候选蓝 / 普通灰。"""
    if p.get("is_waste"):
        return "#EA6668"
    if p.get("is_best"):
        return "#52C41A"
    if p.get("label") == "P" or (p.get("star") or 0) >= 4:
        return "#FAAD14"
    if p.get("is_candidate"):
        return "#8BC8EA"
    return "#4B5563"


def _filmstrip_html(members: list[dict], thumb_size: int = 150) -> str:
    """生成单行可横向滚动的胶片条（base64 缩略图 + 状态彩色边框 + 文件名）。"""
    items = []
    for m in members:
        tp = thumb_of(m["path"], thumb_size)
        if not tp:
            continue
        try:
            b64 = base64.b64encode(open(tp, "rb").read()).decode("ascii")
        except Exception:
            continue
        color = _fs_color(m)
        fname = os.path.basename(m["path"])[:24]
        items.append(
            f"<div style='flex:0 0 auto;text-align:center;'>"
            f"<img src='data:image/jpeg;base64,{b64}' style='width:{thumb_size}px;height:100px;"
            f"object-fit:cover;border-radius:8px;border:3px solid {color};display:block;box-sizing:border-box;'/>"
            f"<div style='font-size:10px;color:#9aa3af;width:{thumb_size}px;margin-top:2px;"
            f"overflow:hidden;text-overflow:ellipsis;white-space:nowrap;'>{fname}</div>"
            f"</div>")
    if not items:
        return ""
    return (f"<div style='display:flex;gap:8px;overflow-x:auto;padding:4px 0 6px 0;"
            f"max-width:100%;box-sizing:border-box;'>{''.join(items)}</div>")


def meta_line(p: dict) -> str:
    return (f"{p.get('scene','')} {p.get('scene_conf',0):.0%} · "
            f"分 {p.get('comp_score',0):.0f} · {p.get('fname','')}")


def analysis_summary_html(res: dict) -> str:
    if not res:
        return ""
    aes = res.get("aesthetic_model") or ""
    q = res.get("quality_model") or ""
    eye = res.get("eye_model") or ""
    aes_txt = f" · 美学 {aes}" if aes else ""
    q_txt = f" · 质量 {q}" if q else ""
    eye_txt = f" · 闭眼 {eye}" if eye else ""
    return (f"<span style='color:#94D8C3'>分析完成：</span>"
            f"{res.get('total',0)} 张 → {res.get('groups',0)} 组 · "
            f"废片 {res.get('waste',0)} · 推荐组 {res.get('best_groups',0)} · "
            f"待甄选组 {res.get('uncertain_groups',0)} · 候选 {res.get('candidate_photos',0)} · "
            f"耗时 {res.get('elapsed',0):.0f}s"
            f"<span style='color:#8BC8EA'>{aes_txt}{q_txt}{eye_txt}</span>")


# ---------------------------------------------------------------------------
# ① 导入页
# ---------------------------------------------------------------------------
def import_page():
    st.markdown(f"### {APP_TITLE}")
    st.markdown("本地 AI 智能选片：**废片剔除 → 相似组 → 场景自适应评分 → 最佳帧推荐 → 不确定甄选**。"
                "照片全程本地处理，不上传。")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### 📁 方式一：选择本地文件夹")
        folder = st.text_input("输入照片目录绝对路径", key="inp_folder",
                               placeholder="如 D:\\PHOTO\\my_photos")
        if folder and os.path.isdir(folder):
            n = len(loader.scan_directory(folder))
            st.caption(f"检测到 {n} 张图片（JPEG/PNG，RAW 可选）")
        elif folder:
            st.error("目录不存在，请检查路径")
        if st.button("▶ 开始分析该文件夹", type="primary", width="stretch",
                     disabled=not (folder and os.path.isdir(folder))):
            st.session_state["source"] = folder.strip()
            st.session_state["source_kind"] = "folder"
            st.session_state["review_idx"] = 0
            st.session_state["undo_stack"] = []
            st.session_state["analyzing"] = True
            go("analyzing")

    with c2:
        st.markdown("#### ☁ 方式二：上传照片")
        files = st.file_uploader("选择多张照片上传", type=["jpg", "jpeg", "png"],
                                 accept_multiple_files=True)
        if files:
            st.caption(f"已选 {len(files)} 张，点击下方按钮开始分析")
        if st.button("▶ 上传并分析", type="primary", width="stretch",
                     disabled=not files):
            run_dir = os.path.join(UPLOAD_ROOT, f"run_{int(time.time())}")
            os.makedirs(run_dir, exist_ok=True)
            saved = 0
            for f in files:
                ext = os.path.splitext(f.name)[1].lower() or ".jpg"
                dst = os.path.join(run_dir, f"{saved:04d}{ext}")
                with open(dst, "wb") as fp:
                    fp.write(f.getbuffer())
                saved += 1
            st.session_state["source"] = run_dir
            st.session_state["source_kind"] = "upload"
            st.session_state["review_idx"] = 0
            st.session_state["undo_stack"] = []
            st.session_state["analyzing"] = True
            go("analyzing")

    st.divider()
    if st.button("✨ 载入演示数据集（28 张，含人像/风光/闭眼/相似组）"):
        st.session_state["source"] = DEMO_DIR
        st.session_state["source_kind"] = "demo"
        st.session_state["review_idx"] = 0
        st.session_state["undo_stack"] = []
        st.session_state["analyzing"] = True
        go("analyzing")


# ---------------------------------------------------------------------------
# ② 自动分析页
# ---------------------------------------------------------------------------
def analyzing_page():
    st.markdown("### ② 自动分析")
    source = st.session_state.get("source", "")
    if not source or not os.path.isdir(source):
        st.warning("尚未选择照片目录。")
        if st.button("← 返回导入"):
            go("import")
        return

    bar = st.progress(0.0, text="准备…")
    status = st.empty()
    st.caption(f"正在分析：{source}")

    phases = config.PHASES
    done_map = {}

    def cb(phase, done, total):
        done_map[phase] = (done, total)
        d, t = done_map.get(phase, (0, 1))
        frac = d / t if t else 0
        bar.progress(min(frac, 1.0), text=f"{phase}：{d}/{t}")
        status.caption(" | ".join(f"{p}:{done_map.get(p,(0,1))[0]}/{done_map.get(p,(0,1))[1]}"
                                  for p in phases if p in done_map))

    s = st.session_state
    try:
        res = analyze_directory(
            source, s["db_path"], use_faces=True, progress_cb=cb,
            burst_interval_ms=s.get("p_burst"), phash_threshold=s.get("p_phash"),
            score_gap=s.get("p_gap"), scene_conf_low=s.get("p_conf"))
    except Exception as e:
        st.error(f"分析出错：{e}")
        st.button("← 返回导入", on_click=lambda: go("import"))
        return

    s["analyzing"] = False
    s["analysis"] = res
    # 自动跳转到人工复核（该页顶部会显示本次分析摘要）
    go("review")


# ---------------------------------------------------------------------------
# ③ 人工复核页（大图横向对比 + 胶片条 + 总览排行榜）
# ---------------------------------------------------------------------------
def review_page():
    res = st.session_state.get("analysis")
    if res:
        st.markdown(f"<div style='padding:8px 12px;border-radius:8px;background:rgba(148,216,195,0.10);"
                    f"border:1px solid rgba(148,216,195,0.25);font-size:13px;margin-bottom:8px;'>"
                    f"{analysis_summary_html(res)}</div>", unsafe_allow_html=True)

    mode = st.radio("查看模式", ["待甄选队列", "总览排行榜"], horizontal=True,
                    key="review_mode")
    if mode == "总览排行榜":
        overview_page()
        return

    # ---- 待甄选队列（原流程）----
    with PhotoStore(st.session_state["db_path"]) as s:
        groups = s.uncertain_groups()
    if not groups:
        st.success("🎉 没有需要人工甄选的组——所有相似组都已自动推荐最佳帧。")
        if st.button("→ 前往确认导出", type="primary"):
            go("confirm")
        overview_page()
        return

    n_groups = len(groups)
    idx = st.session_state.get("review_idx", 0)
    if idx < 0:
        idx = 0
        st.session_state["review_idx"] = 0
    idx = min(idx, n_groups - 1)
    g, cands = _current_group()

    # 进度
    st.progress((idx + 1) / n_groups,
                text=f"待甄选组 {idx + 1}/{n_groups} · 组{g['id']} 共 {g.get('size',0)} 张，候选 {len(cands)} 张")

    # ---- 大图横向对比（每行最多 3 张，图更大）----
    st.markdown(f"#### 大图横向对比（组 {g['id']} 的候选）")
    if cands:
        for row_start in range(0, len(cands), 3):
            row = cands[row_start:row_start + 3]
            cols = st.columns(len(row))
            for j, c in enumerate(row):
                i = row_start + j
                with cols[j]:
                    tag = "ABCD"[i] if i < 4 else "·"
                    st.image(thumb_of(c["path"], config.THUMB_MAX_SIZE), width="stretch")
                    st.caption(f"**{tag}** · {meta_line(c)} · {badge(c)}")
                    if st.button(f"选此张（★5+P）", key=f"pick_{g['id']}_{i}", width="stretch"):
                        _pick_candidate(i)
    else:
        st.info("该组没有可用候选。")

    # ---- 本组全部成员：单行可滚动胶片条 ----
    st.markdown("#### 本组全部成员 · 胶片条（单行，可横向滚动）")
    with PhotoStore(st.session_state["db_path"]) as s:
        members = s.group_members(g["id"])
    st.markdown(_filmstrip_html(members), unsafe_allow_html=True)
    # 单行动作按钮（与胶片条顺序一一对应）
    if members:
        cols = st.columns(len(members))
        for i, m in enumerate(members):
            with cols[i]:
                b1, b2 = st.columns(2, gap="small")
                with b1:
                    if st.button("★", key=f"fs_star_{m['path']}", help=f"标 5 星：{m['fname']}"):
                        _set_star(m["path"], 5); st.rerun()
                with b2:
                    if st.button("✕", key=f"fs_x_{m['path']}", help=f"排除：{m['fname']}"):
                        _set_label(m["path"], "X"); st.rerun()

    # ---- 操作行 ----
    st.divider()
    st.markdown("<div class='kb-row'>先点击下方输入框聚焦，再用快捷键："
                "0-5 标星 · P 保留 / X 排除 · A/B/C/D 选候选 · Tab/→ 下一组 · ← 上一组 · Esc 退出</div>",
                unsafe_allow_html=True)
    kb_widget()
    b1, b2, b3, b4 = st.columns([1, 1, 1, 1])
    if b1.button("← 上一组", width="stretch"):
        _prev_review_group()
    if b2.button("跳过 → 下一组", width="stretch"):
        _next_review_group()
    if b3.button("↩ 撤销上一步", width="stretch", disabled=not st.session_state["undo_stack"]):
        _undo()
    if b4.button("完成甄选 → 确认", type="primary", width="stretch"):
        go("confirm")


# ---------------------------------------------------------------------------
# 总览排行榜（全局评分排序 + 过滤 + 场景手动修正）
# ---------------------------------------------------------------------------
def overview_page():
    st.markdown("#### 总览 · 全局评分排行榜")
    with PhotoStore(st.session_state["db_path"]) as s:
        photos = s.all_photos()

    # ---- 过滤与排序 ----
    c1, c2, c3, c4, c5 = st.columns([1.4, 1.2, 0.8, 1.2, 1.2])
    scenes = sorted({p.get("scene") or "其他" for p in photos})
    sel_scene = c1.multiselect("场景", scenes, default=scenes, key="ov_scene")
    star_min = c2.slider("最低星级", 0, 5, 0, key="ov_star")
    show_waste = c3.checkbox("显示废片", value=True, key="ov_waste")
    only_best = c3.checkbox("仅推荐帧", value=False, key="ov_best")
    sort_key = c4.selectbox("排序", ["综合分↓", "综合分↑", "拍摄时间↓", "拍摄时间↑",
                                     "星级↓", "文件名"], key="ov_sort")
    search = c5.text_input("搜索文件名", "", key="ov_search")

    def _apply(p: dict) -> bool:
        if (p.get("scene") or "其他") not in sel_scene:
            return False
        if (p.get("star") or 0) < star_min:
            return False
        if not show_waste and p.get("is_waste"):
            return False
        if only_best and not p.get("is_best"):
            return False
        if search and search.lower() not in (p.get("fname") or "").lower():
            return False
        return True

    filtered = [p for p in photos if _apply(p)]
    _sort_map = {
        "综合分↓": ("comp_score", True), "综合分↑": ("comp_score", False),
        "拍摄时间↓": ("ts", True), "拍摄时间↑": ("ts", False),
        "星级↓": ("star", True), "文件名": ("fname", False),
    }
    key, rev = _sort_map[sort_key]
    filtered.sort(key=lambda p: (p.get(key) is None, p.get(key) or 0), reverse=rev)

    m1, m2, m3 = st.columns(3)
    m1.metric("全部照片", len(photos))
    m2.metric("过滤后", len(filtered))
    m3.metric("已选（★≥4 或 P）", sum(1 for p in photos
                                        if (p.get("star") or 0) >= 4 or p.get("label") == "P"))

    # ---- 网格展示（含场景修正 + 快捷标星/排除）----
    if not filtered:
        st.info("没有符合条件的照片，请调整过滤条件。")
        return
    limit = st.slider("每页显示张数（大集限流，避免界面卡顿）", 20, min(500, len(filtered)),
                      min(200, len(filtered)), step=20, key="ov_limit")
    shown = filtered[:limit]
    st.caption(f"显示 {len(shown)}/{len(filtered)} 张（按当前排序）。")
    cols = st.columns(5)
    for i, p in enumerate(shown):
        with cols[i % 5]:
            tp = thumb_of(p["path"], 200)
            if tp:
                st.image(tp, width="stretch")
            st.caption(f"{meta_line(p)} · {badge(p)}")
            cur_scene = p.get("scene_manual") or ("自动" if not p.get("scene") else p.get("scene"))
            new_scene = st.selectbox("场景", SCENE_OPTIONS, index=SCENE_OPTIONS.index(cur_scene)
                                     if cur_scene in SCENE_OPTIONS else 0,
                                     key=f"ov_scene_{p['path']}", label_visibility="collapsed")
            if new_scene != cur_scene:
                _set_scene(p["path"], new_scene)
                st.rerun()
            b1, b2 = st.columns(2, gap="small")
            with b1:
                if st.button("★5", key=f"ov_star_{p['path']}"):
                    _set_star(p["path"], 5); st.rerun()
            with b2:
                if st.button("✕", key=f"ov_x_{p['path']}"):
                    _set_label(p["path"], "X"); st.rerun()
    if len(filtered) > limit:
        st.caption(f"… 还有 {len(filtered) - limit} 张未显示，请提高“每页显示张数”。")


# ---------------------------------------------------------------------------
# ④ 确认导出页
# ---------------------------------------------------------------------------
def confirm_page():
    st.markdown("### ④ 确认导出 · 检查所有选中照片")
    with PhotoStore(st.session_state["db_path"]) as s:
        photos = s.all_photos()
        selected = [p for p in photos if (p.get("star") or 0) >= 4 or p.get("label") == "P"]
        wastes = [p for p in photos if p.get("is_waste")]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("总照片", len(photos))
    m2.metric("已选中", len(selected))
    m3.metric("废片（已剔除）", len(wastes))
    with PhotoStore(st.session_state["db_path"]) as s:
        m4.metric("待甄选组", len(s.uncertain_groups()))

    st.markdown("#### 已选中的照片（★≥4 或 P）")
    if not selected:
        st.info("还没有选中任何照片，请先在“人工复核”中甄选。")
    else:
        cols = st.columns(4)
        for i, p in enumerate(selected):
            with cols[i % 4]:
                st.image(thumb_of(p["path"], 420), width="stretch")
                st.caption(f"{meta_line(p)} · {badge(p)}")
                if st.button("移除", key=f"rm_{i}"):
                    _set_star(p["path"], 0)
                    _set_label(p["path"], "")
                    st.rerun()

    st.divider()
    st.markdown("#### 导出")
    export_dir = st.text_input("导出目录（默认 data/export）",
                               value=os.path.join(config.DATA_DIR, "export"))
    fmt = st.selectbox("导出内容", ["保留清单（★≥4 或 P）", "全部清单", "废片清单"])
    kind = st.radio("导出方式", ["CSV 清单", "复制文件到导出目录"], horizontal=True)
    if st.button("导出", type="primary"):
        os.makedirs(export_dir, exist_ok=True)
        if fmt == "保留清单（★≥4 或 P）":
            out_photos = selected
        elif fmt == "废片清单":
            out_photos = wastes
        else:
            out_photos = photos
        csv_path = os.path.join(export_dir, config.EXPORT_CSV_NAME)
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["文件名", "路径", "场景", "场景置信度", "综合分", "星级",
                        "标签", "废片原因", "最佳", "组ID", "模糊", "过曝", "欠曝", "美学"])
            for p in out_photos:
                w.writerow([p.get("fname"), p.get("path"), p.get("scene"),
                            round(p.get("scene_conf") or 0, 3), round(p.get("comp_score") or 0, 1),
                            p.get("star") or 0, p.get("label") or "",
                            p.get("waste_reasons") or "", 1 if p.get("is_best") else 0,
                            p.get("group_id"), round(p.get("blur_score") or 0, 1),
                            round(p.get("over_ratio") or 0, 3), round(p.get("under_ratio") or 0, 3),
                            round(p.get("aesthetic") or 0, 1)])
        msg = f"已导出 {len(out_photos)} 张 → {csv_path}"
        if kind == "复制文件到导出目录":
            sub = os.path.join(export_dir, config.EXPORT_SUBDIR)
            os.makedirs(sub, exist_ok=True)
            copied = 0
            for p in out_photos:
                try:
                    shutil.copy2(p["path"], os.path.join(sub, p["fname"]))
                    copied += 1
                except Exception:
                    pass
            msg += f"；已复制 {copied} 个文件到 {sub}"
        st.success(msg)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def main():
    inject_css()
    sidebar()
    stepper()
    page = st.session_state.get("page", "import")
    if page == "import":
        import_page()
    elif page == "analyzing":
        analyzing_page()
    elif page == "review":
        review_page()
    elif page == "confirm":
        confirm_page()


if __name__ == "__main__":
    main()
