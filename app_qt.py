# -*- coding: utf-8 -*-
"""
app_qt.py —— 光影选片助手（Smart Cull Assistant）桌面版（PyQt6）

原生 Windows 桌面窗口（不依赖浏览器），四阶段向导：
    ① 导入 → ② 自动分析 → ③ 人工复核 → ④ 确认导出

设计要点（成熟软件形态）：
    - 左侧导航 + 右侧内容页；统一深色主题
    - 原生文件夹选择对话框（非网页文本输入）
    - 后台 QThread 分析：实时进度 + 可取消 + 断点续跑
    - 复核页：候选大图并排 + 胶片条 + 键盘快捷键（0-5/P/X/A/B/C/D/←/→/Esc）
    - 总览排行榜：表格 + 场景过滤 + 场景手动修正 + 排序
    - 不展示任何阈值参数（全部走 engine/config.py 默认值，界面保持干净）

引擎全部复用 engine/；本文件只负责 GUI。
运行：.venv/Scripts/python.exe app_qt.py
"""
from __future__ import annotations

import csv
import os
import shutil
import sys

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QKeyEvent, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QWidget, QMainWindow, QLabel, QPushButton, QVBoxLayout,
    QHBoxLayout, QGridLayout, QScrollArea, QStackedWidget, QFileDialog,
    QProgressBar, QMessageBox, QListWidget, QListWidgetItem, QSplitter,
    QComboBox, QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QFrame, QSizePolicy, QButtonGroup, QRadioButton,
    QLineEdit, QSpinBox)

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from engine import config, loader, scorer  # noqa: E402
from engine.pipeline import analyze_directory  # noqa: E402
from engine.store import PhotoStore  # noqa: E402

try:
    from engine import __version__ as APP_VERSION
except Exception:  # noqa: BLE001
    APP_VERSION = "0.2.1"

APP_TITLE = "光影选片助手"
DEFAULT_DB = config.DEFAULT_DB
DEMO_DIR = os.path.join(config.DATA_DIR, "demo")
SCENE_OPTIONS = ["自动", "人像", "风光", "建筑", "街拍", "宠物", "静物", "其他"]

# 主题色（与 Web 版一致）
C_PRIMARY = "#8BC8EA"
C_OK = "#52C41A"
C_WARN = "#FAAD14"
C_DANGER = "#EA6668"
C_BG = "#14161A"
C_BG2 = "#1E2229"
C_TEXT = "#E8EAED"
C_MUTED = "#9aa3af"
C_BORDER = "#2A2F38"

DARK_QSS = f"""
QWidget {{ background-color: {C_BG}; color: {C_TEXT}; font-size: 13px; }}
QMainWindow, QDialog {{ background-color: {C_BG}; }}
QLabel {{ background: transparent; }}
QLabel#PageTitle {{ font-size: 20px; font-weight: 700; color: {C_TEXT}; }}
QLabel#PageSub {{ color: {C_MUTED}; }}
QLabel#NavStep {{ font-size: 14px; padding: 12px 18px; border-radius: 8px; }}
QLabel#NavStep[active="true"] {{ background: rgba(139,200,234,0.16); color: {C_PRIMARY}; font-weight: 700; }}
QLabel#NavStep[active="false"] {{ color: #b8c0cc; }}
QLabel#SectionTitle {{ font-size: 15px; font-weight: 600; color: {C_PRIMARY}; }}
QPushButton {{ background: {C_BG2}; border: 1px solid {C_BORDER}; border-radius: 8px;
               padding: 8px 16px; font-weight: 500; }}
QPushButton:hover {{ border-color: {C_PRIMARY}; }}
QPushButton:disabled {{ color: #5a6270; border-color: {C_BORDER}; }}
QPushButton#Primary {{ background: #2d5d7a; border: 1px solid {C_PRIMARY}; color: white; }}
QPushButton#Primary:hover {{ background: #36708f; }}
QPushButton#Danger {{ color: {C_DANGER}; border-color: #6b3436; }}
QPushButton#Danger:hover {{ background: #3a1f21; }}
QProgressBar {{ border: 1px solid {C_BORDER}; border-radius: 8px; background: {C_BG2};
               height: 18px; text-align: center; color: {C_TEXT}; }}
QProgressBar::chunk {{ background: {C_PRIMARY}; border-radius: 7px; }}
QListWidget {{ background: {C_BG2}; border: 1px solid {C_BORDER}; border-radius: 8px; }}
QListWidget::item {{ padding: 10px; border-radius: 6px; }}
QListWidget::item:selected {{ background: #2d5d7a; }}
QTableWidget {{ background: {C_BG2}; border: 1px solid {C_BORDER}; border-radius: 8px;
               gridline-color: {C_BORDER}; }}
QHeaderView::section {{ background: {C_BG2}; color: {C_TEXT}; border: none;
                        border-bottom: 1px solid {C_BORDER}; padding: 6px; font-weight: 600; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: {C_BG}; width: 10px; }}
QScrollBar::handle:vertical {{ background: #3a4150; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QComboBox, QLineEdit, QSpinBox {{ background: {C_BG2}; border: 1px solid {C_BORDER};
                                  border-radius: 6px; padding: 5px 8px; }}
QComboBox::drop-down {{ border: none; }}
QCheckBox {{ background: transparent; }}
QFrame#Card {{ background: {C_BG2}; border: 1px solid {C_BORDER}; border-radius: 10px; }}
QLabel#Metric {{ font-size: 24px; font-weight: 700; color: {C_PRIMARY}; }}
QLabel#MetricLabel {{ color: {C_MUTED}; font-size: 12px; }}
QStatusBar {{ background: {C_BG2}; color: {C_MUTED}; }}
"""


# ---------------------------------------------------------------------------
# 后台分析线程
# ---------------------------------------------------------------------------
class AnalyzeWorker(QThread):
    progress = pyqtSignal(str, int, int)   # phase, done, total
    succeeded = pyqtSignal(dict)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, source: str, db_path: str, parent=None):
        super().__init__(parent)
        self.source = source
        self.db_path = db_path
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            res = analyze_directory(
                self.source, self.db_path, use_faces=True,
                progress_cb=lambda ph, d, t: self.progress.emit(ph, d, t),
                cancel_check=lambda: self._cancel)
            if res and res.get("cancelled"):
                self.cancelled.emit()
            else:
                self.succeeded.emit(res)
        except Exception as e:  # noqa: BLE001 —— GUI 统一兜底
            self.failed.emit(str(e))


# ---------------------------------------------------------------------------
# 通用小组件
# ---------------------------------------------------------------------------
def _thumb_label(path: str, w: int = 240, h: int = 160) -> QLabel:
    lb = QLabel()
    lb.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lb.setFixedSize(w, h)
    lb.setStyleSheet(f"background:{C_BG2};border:1px solid {C_BORDER};border-radius:8px;")
    tp = loader.make_thumbnail(path, size=max(w, h))
    if tp:
        pix = QPixmap(tp)
        if not pix.isNull():
            lb.setPixmap(pix.scaled(w - 8, h - 8, Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation))
    return lb


def _fs_color(p: dict) -> str:
    if p.get("is_waste"):
        return C_DANGER
    if p.get("is_best"):
        return C_OK
    if p.get("label") == "P" or (p.get("star") or 0) >= 4:
        return C_WARN
    if p.get("is_candidate"):
        return C_PRIMARY
    return C_BORDER


def _badge(p: dict) -> str:
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


def _meta_line(p: dict) -> str:
    return (f"{p.get('scene','')} {p.get('scene_conf',0):.0%} · "
            f"分 {p.get('comp_score',0):.0f} · {p.get('fname','')}")


class MetricCard(QFrame):
    def __init__(self, label: str, value: str):
        super().__init__()
        self.setObjectName("Card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        v = QLabel(value)
        v.setObjectName("Metric")
        l = QLabel(label)
        l.setObjectName("MetricLabel")
        lay.addWidget(v)
        lay.addWidget(l)


# ---------------------------------------------------------------------------
# ① 导入页
# ---------------------------------------------------------------------------
class ImportPage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.folder = ""
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 16, 28, 16)
        lay.setSpacing(12)

        t = QLabel("① 导入照片")
        t.setObjectName("PageTitle")
        sub = QLabel("选择照片文件夹，本地 AI 自动完成：废片剔除 → 相似分组 → 场景评分 → 最佳帧推荐 → 不确定甄选。照片全程本地处理。")
        sub.setObjectName("PageSub")
        sub.setWordWrap(True)
        lay.addWidget(t)
        lay.addWidget(sub)
        lay.addSpacing(8)

        card = QFrame()
        card.setObjectName("Card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 18, 20, 18)
        cl.setSpacing(14)
        row = QHBoxLayout()
        self.folder_label = QLabel("未选择文件夹")
        self.folder_label.setStyleSheet("color:" + C_MUTED)
        self.folder_label.setWordWrap(True)
        btn_browse = QPushButton("选择照片文件夹…")
        btn_browse.clicked.connect(self._browse)
        row.addWidget(self.folder_label, 1)
        row.addWidget(btn_browse)
        cl.addLayout(row)
        self.count_label = QLabel("")
        self.count_label.setStyleSheet("color:" + C_MUTED)
        cl.addWidget(self.count_label)
        lay.addWidget(card)

        lay.addSpacing(6)
        btns = QHBoxLayout()
        self.start_btn = QPushButton("▶ 开始分析")
        self.start_btn.setObjectName("Primary")
        self.start_btn.setEnabled(False)
        self.start_btn.clicked.connect(self._start)
        btn_demo = QPushButton("✨ 载入演示数据集（28 张）")
        btn_demo.clicked.connect(self._demo)
        btns.addWidget(self.start_btn, 1)
        btns.addWidget(btn_demo)
        lay.addLayout(btns)
        lay.addStretch(1)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "选择照片文件夹",
                                             self.folder or "D:\\PHOTO",
                                             QFileDialog.Option.ShowDirsOnly)
        if d:
            self.set_folder(d)

    def set_folder(self, folder: str):
        self.folder = folder
        self.folder_label.setText(folder)
        n = len(loader.scan_directory(folder)) if os.path.isdir(folder) else 0
        self.count_label.setText(f"检测到 {n} 张图片（JPEG/PNG，RAW 可选）" if os.path.isdir(folder) else "目录无效")
        self.start_btn.setEnabled(os.path.isdir(folder) and n > 0)
        self.app.status(f"已选择：{folder}（{n} 张）")

    def _demo(self):
        self.set_folder(DEMO_DIR)
        self._start()

    def _start(self):
        if not os.path.isdir(self.folder):
            return
        self.app.begin_analysis(self.folder)


# ---------------------------------------------------------------------------
# ② 自动分析页
# ---------------------------------------------------------------------------
class AnalyzePage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 16, 28, 16)
        lay.setSpacing(14)
        t = QLabel("② 自动分析")
        t.setObjectName("PageTitle")
        lay.addWidget(t)
        self.sub = QLabel("")
        self.sub.setObjectName("PageSub")
        self.sub.setWordWrap(True)
        lay.addWidget(self.sub)
        lay.addSpacing(10)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        lay.addWidget(self.bar)
        self.status = QLabel("准备中…")
        self.status.setStyleSheet("color:" + C_MUTED)
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        lay.addSpacing(8)
        self.cancel_btn = QPushButton("⏹ 取消分析")
        self.cancel_btn.setObjectName("Danger")
        self.cancel_btn.clicked.connect(self._cancel)
        lay.addWidget(self.cancel_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        tip = QLabel("支持断点续跑：中途取消/关闭后，重新分析同一目录只会补算缺失部分。")
        tip.setStyleSheet("color:" + C_MUTED)
        lay.addWidget(tip)
        lay.addStretch(1)

    def start(self, source: str):
        self.sub.setText(f"正在分析：{source}")
        self.bar.setValue(0)
        self.status.setText("准备中…")
        self.cancel_btn.setEnabled(True)
        self.worker = AnalyzeWorker(source, self.app.db_path, self)
        self.worker.progress.connect(self._on_progress)
        self.worker.succeeded.connect(self._on_done)
        self.worker.failed.connect(self._on_fail)
        self.worker.cancelled.connect(self._on_cancel)
        self.worker.start()

    def _on_progress(self, phase, done, total):
        pct = int(done / total * 100) if total else 0
        self.bar.setValue(min(pct, 100))
        self.status.setText(f"{phase}：{done}/{total}")

    def _on_done(self, res):
        self.bar.setValue(100)
        self.status.setText(self.app.summary_text(res))
        self.app.finish_analysis(res)

    def _on_fail(self, msg):
        self.cancel_btn.setEnabled(False)
        self.status.setText(f"分析出错：{msg}")
        QMessageBox.critical(self, "分析出错", str(msg))

    def _on_cancel(self):
        self.cancel_btn.setEnabled(False)
        self.status.setText("已取消。已有结果已入库，可重新分析（断点续跑）。")
        self.bar.setValue(0)

    def _cancel(self):
        if getattr(self, "worker", None):
            self.worker.cancel()
            self.cancel_btn.setEnabled(False)
            self.status.setText("正在取消…（等待当前批次完成）")


# ---------------------------------------------------------------------------
# ③ 人工复核页
# ---------------------------------------------------------------------------
class ReviewPage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.groups = []
        self.idx = 0
        self.cands = []
        self.undo_stack = []
        self.overview_rows = []

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 14, 20, 14)
        root.setSpacing(8)

        top = QHBoxLayout()
        t = QLabel("③ 人工复核")
        t.setObjectName("PageTitle")
        self.summary_lb = QLabel("")
        self.summary_lb.setStyleSheet(
            f"background:rgba(82,196,26,0.12);border:1px solid {C_OK};"
            f"border-radius:8px;padding:6px 10px;color:#a8d8a0;")
        top.addWidget(t)
        top.addWidget(self.summary_lb, 1)
        root.addLayout(top)

        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        mode_row = QHBoxLayout()
        rb_queue = QRadioButton("待甄选队列")
        rb_queue.setChecked(True)
        rb_over = QRadioButton("总览排行榜")
        self.mode_group.addButton(rb_queue)
        self.mode_group.addButton(rb_over)
        mode_row.addWidget(rb_queue)
        mode_row.addWidget(rb_over)
        mode_row.addStretch(1)
        root.addLayout(mode_row)
        self.mode_group.buttonClicked.connect(self._switch_mode)

        self.stack = QStackedWidget()
        self.queue_page = self._build_queue_page()
        self.overview_page = self._build_overview_page()
        self.stack.addWidget(self.queue_page)
        self.stack.addWidget(self.overview_page)
        root.addWidget(self.stack, 1)

    # ---- 待甄选队列 ----
    def _build_queue_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(10)
        self.prog_lb = QLabel("")
        self.prog_lb.setObjectName("SectionTitle")
        lay.addWidget(self.prog_lb)
        self.compare_area = QScrollArea()
        self.compare_area.setWidgetResizable(True)
        self.compare_host = QWidget()
        self.compare_lay = QVBoxLayout(self.compare_host)
        self.compare_area.setWidget(self.compare_host)
        lay.addWidget(self.compare_area, 1)

        fs_title = QLabel("本组全部成员 · 胶片条（可横向滚动）")
        fs_title.setObjectName("SectionTitle")
        lay.addWidget(fs_title)
        self.film_area = QScrollArea()
        self.film_area.setWidgetResizable(False)
        self.film_area.setFixedHeight(130)
        self.film_host = QWidget()
        self.film_lay = QHBoxLayout(self.film_host)
        self.film_lay.setContentsMargins(2, 2, 2, 2)
        self.film_lay.setSpacing(6)
        self.film_area.setWidget(self.film_host)
        lay.addWidget(self.film_area)

        kb = QLabel("快捷键：0-5 标星 · P 保留 / X 排除 · A/B/C/D 选候选 · ←/→ 上一组/下一组 · Esc 退出")
        kb.setStyleSheet(f"background:rgba(139,200,234,0.08);border:1px solid rgba(139,200,234,0.25);"
                         f"border-radius:8px;padding:6px 10px;color:{C_MUTED};")
        lay.addWidget(kb)
        btns = QHBoxLayout()
        b_prev = QPushButton("← 上一组")
        b_next = QPushButton("跳过 → 下一组")
        b_undo = QPushButton("↩ 撤销")
        b_done = QPushButton("完成甄选 → 确认")
        b_done.setObjectName("Primary")
        b_prev.clicked.connect(lambda: self._step(-1))
        b_next.clicked.connect(lambda: self._step(1))
        b_undo.clicked.connect(self._undo)
        b_done.clicked.connect(lambda: self.app.goto("export"))
        btns.addWidget(b_prev)
        btns.addWidget(b_next)
        btns.addWidget(b_undo)
        btns.addStretch(1)
        btns.addWidget(b_done)
        lay.addLayout(btns)
        return w

    # ---- 总览排行榜 ----
    def _build_overview_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(8)
        frow = QHBoxLayout()
        self.ov_scene = QComboBox()
        self.ov_star = QSpinBox()
        self.ov_star.setRange(0, 5)
        self.ov_waste = QCheckBox("显示废片")
        self.ov_waste.setChecked(True)
        self.ov_best = QCheckBox("仅推荐帧")
        self.ov_sort = QComboBox()
        self.ov_sort.addItems(["综合分↓", "综合分↑", "拍摄时间↓", "拍摄时间↑", "星级↓", "文件名"])
        self.ov_search = QLineEdit()
        self.ov_search.setPlaceholderText("搜索文件名")
        frow.addWidget(QLabel("场景"))
        frow.addWidget(self.ov_scene)
        frow.addWidget(QLabel("最低星级"))
        frow.addWidget(self.ov_star)
        frow.addWidget(self.ov_waste)
        frow.addWidget(self.ov_best)
        frow.addWidget(QLabel("排序"))
        frow.addWidget(self.ov_sort)
        frow.addWidget(self.ov_search, 1)
        lay.addLayout(frow)
        for c in (self.ov_scene, self.ov_star, self.ov_sort, self.ov_search):
            try:
                c.currentIndexChanged.connect(self._refresh_overview)
            except Exception:
                pass
        self.ov_waste.toggled.connect(self._refresh_overview)
        self.ov_best.toggled.connect(self._refresh_overview)
        self.ov_star.valueChanged.connect(self._refresh_overview)
        self.ov_search.textChanged.connect(self._refresh_overview)

        self.ov_table = QTableWidget(0, 7)
        self.ov_table.setHorizontalHeaderLabels(["缩略图", "文件", "场景", "综合分", "星级", "标签", "操作"])
        self.ov_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.ov_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.ov_table.setColumnWidth(0, 120)
        self.ov_table.verticalHeader().setVisible(False)
        self.ov_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.ov_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        lay.addWidget(self.ov_table, 1)
        return w

    # ---- 数据加载 ----
    def reload(self, res: dict | None = None):
        if res:
            self.summary_lb.setText(self.app.summary_text(res))
            self.summary_lb.setVisible(True)
        with PhotoStore(self.app.db_path) as s:
            self.groups = s.uncertain_groups()
        self.idx = 0
        self.undo_stack = []
        self._show_queue()

    def _switch_mode(self, btn):
        if btn.text() == "总览排行榜":
            self.stack.setCurrentWidget(self.overview_page)
            self._refresh_overview()
        else:
            self.stack.setCurrentWidget(self.queue_page)
            self._show_queue()

    def _load_group(self):
        if not self.groups:
            self.cands = []
            return
        self.idx = max(0, min(self.idx, len(self.groups) - 1))
        with PhotoStore(self.app.db_path) as s:
            g = self.groups[self.idx]
            self.cands = s.candidates(g["id"])

    def _show_queue(self):
        # 清空
        while self.compare_lay.count():
            it = self.compare_lay.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        while self.film_lay.count():
            it = self.film_lay.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        if not self.groups:
            self.prog_lb.setText("🎉 没有需要人工甄选的组——所有相似组都已自动推荐最佳帧。")
            return
        self._load_group()
        g = self.groups[self.idx]
        self.prog_lb.setText(f"待甄选组 {self.idx + 1}/{len(self.groups)} · 组 {g['id']} 共 {g.get('size', 0)} 张，候选 {len(self.cands)} 张")
        # 候选大图（每行最多 3 张）
        if self.cands:
            for r in range(0, len(self.cands), 3):
                row_lay = QHBoxLayout()
                row_lay.setSpacing(10)
                for j, c in enumerate(self.cands[r:r + 3]):
                    i = r + j
                    col = QVBoxLayout()
                    col.setSpacing(4)
                    tag = "ABCD"[i] if i < 4 else "·"
                    col.addWidget(_thumb_label(c["path"], 300, 200))
                    cap = QLabel(f"**{tag}** {_meta_line(c)} · {_badge(c)}")
                    cap.setStyleSheet(f"color:{C_MUTED};font-size:12px;")
                    cap.setWordWrap(True)
                    col.addWidget(cap)
                    pb = QPushButton(f"选此张（★5+P）")
                    pb.clicked.connect(lambda _, x=i: self._pick_candidate(x))
                    col.addWidget(pb)
                    row_lay.addLayout(col)
                self.compare_lay.addLayout(row_lay)
        else:
            self.compare_lay.addWidget(QLabel("该组没有可用候选。"))
        # 胶片条
        with PhotoStore(self.app.db_path) as s:
            members = s.group_members(g["id"])
        for m in members:
            card = QFrame()
            card.setFixedWidth(120)
            card.setStyleSheet(f"background:{C_BG2};border:2px solid {_fs_color(m)};border-radius:8px;")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(4, 4, 4, 4)
            cl.setSpacing(2)
            cl.addWidget(_thumb_label(m["path"], 108, 72))
            fn = QLabel(os.path.basename(m["path"])[:16])
            fn.setStyleSheet(f"color:{C_MUTED};font-size:10px;")
            fn.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cl.addWidget(fn)
            # 快捷按钮
            brow = QHBoxLayout()
            bs = QPushButton("★")
            bs.setFixedHeight(22)
            bs.clicked.connect(lambda _, p=m["path"]: self._set_star(p, 5))
            bx = QPushButton("✕")
            bx.setFixedHeight(22)
            bx.clicked.connect(lambda _, p=m["path"]: self._set_label(p, "X"))
            brow.addWidget(bs)
            brow.addWidget(bx)
            cl.addLayout(brow)
            self.film_lay.addWidget(card)
        self.film_lay.addStretch(1)

    # ---- 数据操作（带撤销）----
    def _set_star(self, path: str, star: int):
        with PhotoStore(self.app.db_path) as s:
            old = (s.get_photo(path) or {}).get("star", 0)
            s.set_star(path, star)
        self.undo_stack.append(("star", path, old, star))
        self._show_queue()

    def _set_label(self, path: str, label: str):
        with PhotoStore(self.app.db_path) as s:
            old = (s.get_photo(path) or {}).get("label") or ""
            s.set_pick(path, label)
        self.undo_stack.append(("label", path, old, label))
        self._show_queue()

    def _pick_candidate(self, i: int):
        if i < len(self.cands):
            c = self.cands[i]
            self._set_star(c["path"], 5)
            self._set_label(c["path"], "P")
        self._step(1)

    def _step(self, delta: int):
        if not self.groups:
            return
        ni = self.idx + delta
        if ni >= len(self.groups):
            self.idx = -1
            QMessageBox.information(self, "完成", "所有待甄选组已处理完毕，可前往确认导出。")
            self.app.goto("export")
            return
        if ni >= 0:
            self.idx = ni
        self._show_queue()

    def _undo(self):
        if not self.undo_stack:
            return
        kind, path, old, new = self.undo_stack.pop()
        with PhotoStore(self.app.db_path) as s:
            if kind == "star":
                s.set_star(path, old)
            elif kind == "label":
                s.set_label(path, old)
        self._show_queue()

    def keyPressEvent(self, e: QKeyEvent):
        if self.stack.currentWidget() is not self.queue_page:
            super().keyPressEvent(e)
            return
        k = e.key()
        if Qt.Key.Key_0 <= k <= Qt.Key.Key_5:
            self._star_current(int(chr(k)))
        elif k in (Qt.Key.Key_P,):
            self._pick_current("P")
        elif k in (Qt.Key.Key_X,):
            self._pick_current("X")
        elif k == Qt.Key.Key_A:
            self._pick_candidate(0)
        elif k == Qt.Key.Key_B:
            self._pick_candidate(1)
        elif k == Qt.Key.Key_C:
            self._pick_candidate(2)
        elif k == Qt.Key.Key_D:
            self._pick_candidate(3)
        elif k in (Qt.Key.Key_Right, Qt.Key.Key_Tab):
            self._step(1)
        elif k == Qt.Key.Key_Left:
            self._step(-1)
        elif k == Qt.Key.Key_Escape:
            self.idx = -1
        else:
            super().keyPressEvent(e)

    def _star_current(self, star: int):
        if self.cands:
            self._set_star(self.cands[0]["path"], star)

    def _pick_current(self, label: str):
        if self.cands:
            self._set_label(self.cands[0]["path"], label)
            self._step(1)

    # ---- 总览排行榜 ----
    def _refresh_overview(self):
        with PhotoStore(self.app.db_path) as s:
            photos = s.all_photos()
        scenes = sorted({p.get("scene") or "其他" for p in photos})
        self.ov_scene.blockSignals(True)
        self.ov_scene.clear()
        self.ov_scene.addItem("全部")
        self.ov_scene.addItems(scenes)
        self.ov_scene.blockSignals(False)
        sel_scene = self.ov_scene.currentText()
        star_min = self.ov_star.value()
        show_waste = self.ov_waste.isChecked()
        only_best = self.ov_best.isChecked()
        search = self.ov_search.text().strip().lower()

        def keep(p):
            if sel_scene != "全部" and (p.get("scene") or "其他") != sel_scene:
                return False
            if (p.get("star") or 0) < star_min:
                return False
            if not show_waste and p.get("is_waste"):
                return False
            if only_best and not p.get("is_best"):
                return False
            if search and search not in (p.get("fname") or "").lower():
                return False
            return True

        filtered = [p for p in photos if keep(p)]
        smap = {
            "综合分↓": ("comp_score", True), "综合分↑": ("comp_score", False),
            "拍摄时间↓": ("ts", True), "拍摄时间↑": ("ts", False),
            "星级↓": ("star", True), "文件名": ("fname", False),
        }
        key, rev = smap.get(self.ov_sort.currentText(), ("comp_score", True))
        filtered.sort(key=lambda p: (p.get(key) is None, p.get(key) or 0), reverse=rev)
        self.overview_rows = filtered

        self.ov_table.setRowCount(len(filtered))
        for r, p in enumerate(filtered):
            cell_thumb = QWidget()
            th = _thumb_label(p["path"], 110, 74)
            tl = QVBoxLayout(cell_thumb)
            tl.setContentsMargins(2, 2, 2, 2)
            tl.addWidget(th)
            self.ov_table.setCellWidget(r, 0, cell_thumb)
            self.ov_table.setItem(r, 1, QTableWidgetItem(p.get("fname", "")))
            scene_box = QComboBox()
            cur = p.get("scene_manual") or (p.get("scene") or "自动")
            idx = SCENE_OPTIONS.index(cur) if cur in SCENE_OPTIONS else 0
            scene_box.addItems(SCENE_OPTIONS)
            scene_box.setCurrentIndex(idx)
            scene_box.currentIndexChanged.connect(
                lambda _, i, path=p["path"]: self._set_scene(path, SCENE_OPTIONS[i]))
            self.ov_table.setCellWidget(r, 2, scene_box)
            self.ov_table.setItem(r, 3, QTableWidgetItem(f"{p.get('comp_score', 0):.0f}"))
            self.ov_table.setItem(r, 4, QTableWidgetItem(str(p.get("star") or 0)))
            self.ov_table.setItem(r, 5, QTableWidgetItem(_badge(p)))
            op = QWidget()
            ol = QHBoxLayout(op)
            ol.setContentsMargins(2, 2, 2, 2)
            bs = QPushButton("★5")
            bx = QPushButton("✕")
            bs.clicked.connect(lambda _, pp=p["path"]: self._set_star(pp, 5))
            bx.clicked.connect(lambda _, pp=p["path"]: self._set_label(pp, "X"))
            ol.addWidget(bs)
            ol.addWidget(bx)
            self.ov_table.setCellWidget(r, 6, op)
        for c in range(7):
            self.ov_table.resizeRowToContents(r) if filtered else None

    def _set_scene(self, path: str, scene: str):
        with PhotoStore(self.app.db_path) as s:
            s.set_scene_manual(path, None if scene == "自动" else scene)
            if scene != "自动":
                s.update_photo(path, scene=scene, scene_conf=1.0)
        self._refresh_overview()


# ---------------------------------------------------------------------------
# ④ 确认导出页
# ---------------------------------------------------------------------------
class ExportPage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.photos = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 16, 28, 16)
        lay.setSpacing(12)
        t = QLabel("④ 确认导出 · 检查所有选中照片")
        t.setObjectName("PageTitle")
        lay.addWidget(t)

        self.metrics = QHBoxLayout()
        self.m_total = MetricCard("总照片", "0")
        self.m_sel = MetricCard("已选中（★≥4 或 P）", "0")
        self.m_waste = MetricCard("废片（已剔除）", "0")
        self.m_group = MetricCard("待甄选组", "0")
        for m in (self.m_total, self.m_sel, self.m_waste, self.m_group):
            self.metrics.addWidget(m)
        lay.addLayout(self.metrics)

        sec = QLabel("已选中的照片")
        sec.setObjectName("SectionTitle")
        lay.addWidget(sec)
        self.grid_area = QScrollArea()
        self.grid_area.setWidgetResizable(True)
        self.grid_host = QWidget()
        self.grid_lay = QGridLayout(self.grid_host)
        self.grid_area.setWidget(self.grid_host)
        lay.addWidget(self.grid_area, 1)

        ex = QHBoxLayout()
        self.dir_edit = QLineEdit(os.path.join(config.DATA_DIR, "export"))
        lbl_dir = QLabel("导出目录")
        ex.addWidget(lbl_dir)
        ex.addWidget(self.dir_edit, 1)
        btn_dir = QPushButton("浏览…")
        btn_dir.clicked.connect(self._browse_dir)
        ex.addWidget(btn_dir)
        lay.addLayout(ex)
        row2 = QHBoxLayout()
        self.fmt = QComboBox()
        self.fmt.addItems(["保留清单（★≥4 或 P）", "全部清单", "废片清单"])
        self.kind = QComboBox()
        self.kind.addItems(["CSV 清单", "复制文件到导出目录"])
        btn_exp = QPushButton("导出")
        btn_exp.setObjectName("Primary")
        btn_exp.clicked.connect(self._export)
        btn_open = QPushButton("打开导出目录")
        btn_open.clicked.connect(self._open_dir)
        row2.addWidget(QLabel("导出内容"))
        row2.addWidget(self.fmt)
        row2.addWidget(QLabel("方式"))
        row2.addWidget(self.kind)
        row2.addStretch(1)
        row2.addWidget(btn_open)
        row2.addWidget(btn_exp)
        lay.addLayout(row2)
        self.msg = QLabel("")
        self.msg.setStyleSheet(f"color:{C_OK};")
        lay.addWidget(self.msg)

    def reload(self):
        with PhotoStore(self.app.db_path) as s:
            self.photos = s.all_photos()
            selected = [p for p in self.photos if (p.get("star") or 0) >= 4 or p.get("label") == "P"]
            wastes = [p for p in self.photos if p.get("is_waste")]
            ngroup = len(s.uncertain_groups())
        self.m_total.set_value = None  # noop
        self._set_metric(self.m_total, "总照片", str(len(self.photos)))
        self._set_metric(self.m_sel, "已选中（★≥4 或 P）", str(len(selected)))
        self._set_metric(self.m_waste, "废片（已剔除）", str(len(wastes)))
        self._set_metric(self.m_group, "待甄选组", str(ngroup))
        # 清空网格
        while self.grid_lay.count():
            it = self.grid_lay.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        cols = 4
        for i, p in enumerate(selected):
            cell = QWidget()
            cl = QVBoxLayout(cell)
            cl.setSpacing(4)
            cl.addWidget(_thumb_label(p["path"], 220, 150))
            cap = QLabel(f"{_meta_line(p)} · {_badge(p)}")
            cap.setStyleSheet(f"color:{C_MUTED};font-size:11px;")
            cap.setWordWrap(True)
            cl.addWidget(cap)
            rb = QPushButton("移除")
            rb.clicked.connect(lambda _, pp=p["path"]: self._remove(pp))
            cl.addWidget(rb)
            self.grid_lay.addWidget(cell, i // cols, i % cols)
        self.grid_lay.setRowStretch((len(selected) - 1) // cols + 1, 1)

    def _set_metric(self, card: MetricCard, label: str, value: str):
        # 直接更新内部 QLabel
        lay = card.layout()
        lay.itemAt(0).widget().setText(value)
        lay.itemAt(1).widget().setText(label)

    def _remove(self, path: str):
        with PhotoStore(self.app.db_path) as s:
            s.set_star(path, 0)
            s.set_label(path, "")
        self.reload()

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择导出目录", self.dir_edit.text(),
                                             QFileDialog.Option.ShowDirsOnly)
        if d:
            self.dir_edit.setText(d)

    def _export(self):
        export_dir = self.dir_edit.text().strip()
        if not export_dir:
            return
        os.makedirs(export_dir, exist_ok=True)
        selected = [p for p in self.photos if (p.get("star") or 0) >= 4 or p.get("label") == "P"]
        wastes = [p for p in self.photos if p.get("is_waste")]
        fmt = self.fmt.currentText()
        if fmt.startswith("保留"):
            out = selected
        elif fmt.startswith("废片"):
            out = wastes
        else:
            out = self.photos
        csv_path = os.path.join(export_dir, config.EXPORT_CSV_NAME)
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["文件名", "路径", "场景", "场景置信度", "综合分", "星级", "标签",
                        "废片原因", "最佳", "组ID", "模糊", "过曝", "欠曝", "美学"])
            for p in out:
                w.writerow([p.get("fname"), p.get("path"), p.get("scene"),
                            round(p.get("scene_conf") or 0, 3), round(p.get("comp_score") or 0, 1),
                            p.get("star") or 0, p.get("label") or "", p.get("waste_reasons") or "",
                            1 if p.get("is_best") else 0, p.get("group_id"),
                            round(p.get("blur_score") or 0, 1), round(p.get("over_ratio") or 0, 3),
                            round(p.get("under_ratio") or 0, 3), round(p.get("aesthetic") or 0, 1)])
        msg = f"已导出 {len(out)} 张 → {csv_path}"
        if self.kind.currentText().startswith("复制"):
            sub = os.path.join(export_dir, config.EXPORT_SUBDIR)
            os.makedirs(sub, exist_ok=True)
            copied = 0
            for p in out:
                try:
                    shutil.copy2(p["path"], os.path.join(sub, p["fname"]))
                    copied += 1
                except Exception:
                    pass
            msg += f"；已复制 {copied} 个文件到 {sub}"
        self.msg.setText(msg)
        self.app.status(msg)

    def _open_dir(self):
        d = self.dir_edit.text().strip()
        if os.path.isdir(d):
            os.startfile(d)
        else:
            QMessageBox.information(self, "提示", f"目录不存在：{d}")


# ---------------------------------------------------------------------------
# 主窗口
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db_path = DEFAULT_DB
        self.setWindowTitle(APP_TITLE)
        self.resize(1280, 820)
        self.setMinimumSize(1024, 700)

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 左导航
        self.nav = QListWidget()
        self.nav.setFixedWidth(170)
        for name in ["① 导入", "② 自动分析", "③ 人工复核", "④ 确认导出"]:
            it = QListWidgetItem(name)
            self.nav.addItem(it)
        self.nav.currentRowChanged.connect(self._nav_changed)
        root.addWidget(self.nav)

        self.stack = QStackedWidget()
        self.import_page = ImportPage(self)
        self.analyze_page = AnalyzePage(self)
        self.review_page = ReviewPage(self)
        self.export_page = ExportPage(self)
        for p in (self.import_page, self.analyze_page, self.review_page, self.export_page):
            self.stack.addWidget(p)
        root.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.statusBar().showMessage(f"v{APP_VERSION} · 本地处理 · 模型：加载时自动")
        self._device_info()

    def _device_info(self):
        try:
            import torch
            dev = "✅ GPU 推理" if torch.cuda.is_available() else "💻 CPU（自动降级）"
        except Exception:
            dev = "💻 CPU"
        self.statusBar().showMessage(f"v{APP_VERSION} · 推理设备：{dev} · 照片全程本地处理，不上传")

    def status(self, msg: str):
        self.statusBar().showMessage(msg, 8000)

    def summary_text(self, res: dict) -> str:
        if not res:
            return ""
        return (f"分析完成：{res.get('total', 0)} 张 → {res.get('groups', 0)} 组 · "
                f"废片 {res.get('waste', 0)} · 推荐组 {res.get('best_groups', 0)} · "
                f"待甄选组 {res.get('uncertain_groups', 0)} · 候选 {res.get('candidate_photos', 0)} · "
                f"耗时 {res.get('elapsed', 0):.0f}s")

    def _nav_changed(self, row: int):
        if row < 0:
            return
        if row == 3:  # 导出页点击时刷新
            self.export_page.reload()
        if row == 2:  # 复核页点击时刷新
            self.review_page.reload()
        self.stack.setCurrentIndex(row)

    def goto(self, name: str):
        idx = {"import": 0, "analyzing": 1, "review": 2, "export": 3}[name]
        self.nav.setCurrentRow(idx)
        if name == "export":
            self.export_page.reload()
        elif name == "review":
            self.review_page.reload()
        self.stack.setCurrentIndex(idx)

    def begin_analysis(self, source: str):
        self.goto("analyzing")
        self.analyze_page.start(source)

    def finish_analysis(self, res: dict):
        self.review_page.reload(res)
        self.goto("review")
        self.status("分析完成，已进入人工复核。")

    def closeEvent(self, e):
        w = getattr(self.analyze_page, "worker", None)
        if w and w.isRunning():
            w.cancel()
            w.wait(2000)
        super().closeEvent(e)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(DARK_QSS)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
