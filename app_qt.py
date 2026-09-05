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
    QLineEdit, QSpinBox, QDialog)

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

# 浅色主题调色板（冷静专业：蓝绿强调色 + 中性灰，保证对比度与可读）
C_PRIMARY = "#3C7DBF"        # 主强调色（冷静蓝）
C_PRIMARY_DK = "#2C609A"     # 强调色按下态
C_OK = "#2E9E5B"             # 通过/最佳帧
C_WARN = "#C9821B"           # 警告/近似重复
C_DANGER = "#D64550"         # 危险/废片/闭眼
C_BG = "#F4F6F9"             # 应用背景
C_PANEL = "#EEF2F7"          # 次级面板（导航/胶片条）
C_CARD = "#FFFFFF"           # 卡片/面板背景
C_TEXT = "#1F2933"           # 主文字
C_MUTED = "#6B7280"          # 次要文字
C_BORDER = "#E2E8F0"         # 浅边框
C_BORDER2 = "#CBD5E1"        # 略深边框

# 半透明强调底色（用于状态条/提示）
C_OK_SOFT = "rgba(46,158,91,0.12)"
C_WARN_SOFT = "rgba(201,130,27,0.14)"
C_DANGER_SOFT = "rgba(214,69,80,0.12)"
C_PRIMARY_SOFT = "rgba(60,125,191,0.10)"

# 内联回退样式（styles.qss 加载失败时使用，保持浅色一致）
FALLBACK_QSS = f"""
QWidget {{ background-color: {C_BG}; color: {C_TEXT}; font-size: 13px; }}
QMainWindow, QDialog {{ background-color: {C_BG}; }}
QLabel {{ background: transparent; }}
QLabel#PageTitle {{ font-size: 20px; font-weight: 700; color: {C_TEXT}; }}
QLabel#PageSub {{ color: {C_MUTED}; }}
QLabel#SectionTitle {{ font-size: 15px; font-weight: 600; color: {C_PRIMARY}; }}
QLabel#Metric {{ font-size: 24px; font-weight: 700; color: {C_PRIMARY}; }}
QLabel#MetricLabel {{ color: {C_MUTED}; font-size: 12px; }}
QLabel#PopTitle {{ font-size: 13px; font-weight: 700; color: {C_TEXT}; }}
QPushButton {{ background: {C_CARD}; border: 1px solid {C_BORDER2}; border-radius: 8px;
               padding: 8px 16px; font-weight: 500; color: {C_TEXT}; }}
QPushButton:hover {{ border-color: {C_PRIMARY}; color: {C_PRIMARY}; }}
QPushButton:pressed {{ background: {C_PANEL}; }}
QPushButton:disabled {{ color: {C_MUTED}; border-color: {C_BORDER}; }}
QPushButton#Primary {{ background: {C_PRIMARY}; border: 1px solid {C_PRIMARY}; color: white; }}
QPushButton#Primary:hover {{ background: {C_PRIMARY_DK}; color: white; }}
QPushButton#Danger {{ color: {C_DANGER}; border-color: {C_DANGER}; }}
QPushButton#Danger:hover {{ background: {C_DANGER_SOFT}; }}
QPushButton#Ghost {{ background: transparent; border: 1px solid {C_BORDER2}; color: {C_MUTED}; }}
QProgressBar {{ border: 1px solid {C_BORDER}; border-radius: 8px; background: {C_PANEL};
               height: 18px; text-align: center; color: {C_TEXT}; }}
QProgressBar::chunk {{ background: {C_PRIMARY}; border-radius: 7px; }}
QListWidget#Nav {{ background: {C_PANEL}; border: none; border-right: 1px solid {C_BORDER};
                   border-radius: 0; }}
QListWidget#Nav::item {{ padding: 12px 18px; border-radius: 8px; color: {C_TEXT}; }}
QListWidget#Nav::item:selected {{ background: {C_PRIMARY_SOFT}; color: {C_PRIMARY}; font-weight: 700; }}
QListWidget#Nav::item:hover {{ background: {C_BORDER}; }}
QListWidget {{ background: {C_CARD}; border: 1px solid {C_BORDER}; border-radius: 8px; }}
QListWidget::item {{ padding: 10px; border-radius: 6px; }}
QListWidget::item:selected {{ background: {C_PRIMARY}; color: white; }}
QTableWidget {{ background: {C_CARD}; border: 1px solid {C_BORDER}; border-radius: 8px;
               gridline-color: {C_BORDER}; color: {C_TEXT}; }}
QHeaderView::section {{ background: {C_PANEL}; color: {C_TEXT}; border: none;
                        border-bottom: 1px solid {C_BORDER}; padding: 6px; font-weight: 600; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: {C_BG}; width: 10px; }}
QScrollBar::handle:vertical {{ background: {C_BORDER2}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QComboBox, QLineEdit, QSpinBox {{ background: {C_CARD}; border: 1px solid {C_BORDER2};
                                  border-radius: 6px; padding: 5px 8px; color: {C_TEXT}; }}
QComboBox::drop-down {{ border: none; }}
QComboBox QAbstractItemView {{ background: {C_CARD}; color: {C_TEXT};
                               selection-background-color: {C_PRIMARY}; }}
QCheckBox {{ background: transparent; color: {C_TEXT}; spacing: 4px; }}
QRadioButton {{ background: transparent; color: {C_TEXT}; spacing: 4px; }}
QFrame#Card {{ background: {C_CARD}; border: 1px solid {C_BORDER}; border-radius: 10px; }}
QFrame#Popover {{ background: {C_CARD}; border: 1px solid {C_BORDER2}; border-radius: 10px; }}
QPushButton#CollapsibleHead {{ background: {C_PANEL}; border: 1px solid {C_BORDER};
                               border-radius: 8px; text-align: left; padding: 8px 12px;
                               font-weight: 600; color: {C_TEXT}; }}
QPushButton#CollapsibleHead:checked {{ border-color: {C_PRIMARY}; color: {C_PRIMARY}; }}
QStatusBar {{ background: {C_PANEL}; color: {C_MUTED}; }}
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
    lb.setStyleSheet(f"background:{C_CARD};border:1px solid {C_BORDER};border-radius:8px;")
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
    if p.get("is_similar_loser") and not p.get("is_waste"):
        tags.append("近似重复")
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
# 评分可解释性 & 公共小组件
# ---------------------------------------------------------------------------
def _is_closed_eye(p: dict) -> bool:
    """闭眼判定：融合废片原因 / EAR 阈值 / 闭眼分类器概率，口径与引擎一致。"""
    reasons = p.get("waste_reasons") or ""
    if "闭眼" in reasons:
        return True
    ear = p.get("eye_open")
    if ear is not None and ear < config.EAR_CLOSED_THRESHOLD:
        return True
    ep = p.get("eye_close_prob")
    if ep is not None and ep > config.EYE_MODEL_CONF:
        return True
    return False


def _clarity_pct(p: dict) -> int:
    """清晰度百分比：拉普拉斯方差 200 视为满分（与 scorer.norm_blur 同口径）。"""
    b = p.get("blur_score") or 0
    return max(0, min(100, int(b / 200.0 * 100)))


def score_breakdown(p: dict) -> list:
    """返回 [(维度, 展示值, 等级, 说明), ...]，等级: good/warn/bad/muted。"""
    rows = []
    b = p.get("blur_score")
    if b is None:
        rows.append(("清晰度", "—", "muted", "无数据"))
    else:
        pct = _clarity_pct(p)
        if b < 60:
            lvl, desc = "bad", "严重失焦"
        elif b < 120:
            lvl, desc = "warn", "轻微失焦"
        else:
            lvl, desc = "good", "清晰锐利"
        rows.append(("清晰度", f"{pct}/100", lvl, desc))

    over = (p.get("over_ratio") or 0) * 100
    under = (p.get("under_ratio") or 0) * 100
    if over > 50 or under > 50:
        lvl, desc = "bad", "严重过曝/欠曝"
    elif over > 20 or under > 20:
        lvl, desc = "warn", "曝光略偏"
    else:
        lvl, desc = "good", "曝光正常"
    parts = []
    if over > 1:
        parts.append(f"过曝 {over:.0f}%")
    if under > 1:
        parts.append(f"欠曝 {under:.0f}%")
    rows.append(("曝光", " · ".join(parts) if parts else "正常", lvl, desc))

    a = p.get("aesthetic")
    if a is None:
        rows.append(("美学", "—", "muted", "无数据"))
    else:
        lvl = "good" if a >= 60 else ("warn" if a >= 40 else "bad")
        rows.append(("美学", f"{a:.0f}/100", lvl, "构图/色彩观感"))

    if p.get("is_face"):
        if _is_closed_eye(p):
            rows.append(("人脸", "闭眼 ⚠", "bad", f"EAR {p.get('eye_open') or 0:.2f}，建议排除"))
        else:
            rows.append(("人脸", "睁眼 OK", "good", f"EAR {p.get('eye_open') or 0:.2f}"))
    else:
        rows.append(("人脸", "未检测到", "muted", "无人脸"))

    rows.append(("场景", f"{p.get('scene','—')} ({(p.get('scene_conf') or 0):.0%})",
                 "muted", "AI 自动识别"))
    comp = p.get("comp_score")
    if comp is None:
        rows.append(("综合", "—", "muted", "无数据"))
    else:
        lvl = "good" if comp >= 70 else ("warn" if comp >= 50 else "bad")
        rows.append(("综合", f"{comp:.0f}/100", lvl, "加权总分"))

    if p.get("is_similar_loser") and not p.get("is_waste"):
        rows.append(("相似", "本组落败", "warn", "近重复，可找回"))
    return rows


_LEVEL_COLOR = {"good": C_OK, "warn": C_WARN, "bad": C_DANGER, "muted": C_MUTED}


def explain_html(p: dict) -> str:
    """富文本（用于 tooltip）。"""
    rows = "".join(
        f'<tr><td style="color:{C_MUTED};padding:2px 6px;">{name}</td>'
        f'<td style="color:{_LEVEL_COLOR[lvl]};font-weight:600;padding:2px 6px;">{val}</td>'
        f'<td style="color:{C_TEXT};padding:2px 6px;">{desc}</td></tr>'
        for name, val, lvl, desc in score_breakdown(p))
    return (f'<div style="font-size:12px;">'
            f'<div style="font-weight:700;margin-bottom:4px;">'
            f'{os.path.basename(p.get("path","") or "")}</div>'
            f'<table>{rows}</table></div>')


def face_badges(p: dict) -> list:
    """返回 [(文本, 背景色, 前景色), ...]，用于人脸/闭眼/相似落败标记。

    说明：引擎仅持久化 is_face(0/1)、eye_open(EAR)、eye_close_prob，
    未保存人脸数量，因此多脸只以「人脸」徽章表示，无法显示具体数量。"""
    out = []
    if p.get("is_face"):
        if _is_closed_eye(p):
            out.append(("闭眼", C_DANGER, "#FFFFFF"))
        else:
            out.append(("人脸", C_PRIMARY, "#FFFFFF"))
    if p.get("is_similar_loser") and not p.get("is_waste"):
        out.append(("近似重复", C_WARN, "#FFFFFF"))
    return out


def _chip(text: str, bg: str, fg: str) -> QLabel:
    lb = QLabel(text)
    lb.setStyleSheet(
        f"background:{bg};color:{fg};border-radius:6px;padding:1px 7px;"
        f"font-size:11px;font-weight:600;")
    return lb


class ScorePopover(QFrame):
    """点击「评分说明」弹出的可解释评分面板（Popup，点击外部自动关闭）。"""

    def __init__(self, p: dict, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setObjectName("Popover")
        self.setMinimumWidth(300)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        title = QLabel("评分说明 · " + os.path.basename(p.get("path", "") or ""))
        title.setObjectName("PopTitle")
        lay.addWidget(title)
        for name, val, lvl, desc in score_breakdown(p):
            row = QHBoxLayout()
            row.setSpacing(6)
            n = QLabel(name)
            n.setFixedWidth(48)
            n.setStyleSheet(f"color:{C_MUTED};")
            v = QLabel(val)
            v.setFixedWidth(100)
            v.setStyleSheet(f"color:{_LEVEL_COLOR[lvl]};font-weight:600;")
            d = QLabel(desc)
            d.setStyleSheet(f"color:{C_TEXT};")
            row.addWidget(n)
            row.addWidget(v)
            row.addWidget(d, 1)
            lay.addLayout(row)
        self.adjustSize()


class Collapsible(QWidget):
    """可折叠分组：标题栏可点击展开/收起，默认收起。"""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.head = QPushButton("▸ " + title)
        self.head.setObjectName("CollapsibleHead")
        self.head.setCheckable(True)
        self.head.setChecked(False)
        self.body = QWidget()
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(4, 8, 4, 4)
        self.body_lay.setSpacing(8)
        self.body.setVisible(False)
        self.head.toggled.connect(self._on_toggle)
        lay.addWidget(self.head)
        lay.addWidget(self.body)

    def _on_toggle(self, checked: bool):
        self.head.setText(("▾ " if checked else "▸ ") + self.head.text()[2:])
        self.body.setVisible(checked)

    def addWidget(self, w):
        self.body_lay.addWidget(w)

    def clear_body(self):
        while self.body_lay.count():
            it = self.body_lay.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()


class CompareDialog(QDialog):
    """A/B 双图对比：左右并排展示缩略图与评分维度拆解。"""

    def __init__(self, db_path: str, members: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("A/B 对比")
        self.resize(920, 580)
        self.db_path = db_path
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)
        pick = QHBoxLayout()
        self.a_cb = QComboBox()
        self.b_cb = QComboBox()
        for m in members:
            self.a_cb.addItem(os.path.basename(m["path"]), m["path"])
            self.b_cb.addItem(os.path.basename(m["path"]), m["path"])
        if self.a_cb.count() > 1:
            self.b_cb.setCurrentIndex(1)
        pick.addWidget(QLabel("A:"))
        pick.addWidget(self.a_cb, 1)
        pick.addWidget(QLabel("B:"))
        pick.addWidget(self.b_cb, 1)
        btn = QPushButton("对比")
        btn.setObjectName("Primary")
        btn.clicked.connect(self._render)
        pick.addWidget(btn)
        lay.addLayout(pick)
        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        self.host = QWidget()
        self.hl = QHBoxLayout(self.host)
        self.hl.setSpacing(16)
        self.area.setWidget(self.host)
        lay.addWidget(self.area, 1)
        if members:
            self._render()

    def _render(self):
        pa = self.a_cb.currentData()
        pb = self.b_cb.currentData()
        if not pa or not pb:
            return
        with PhotoStore(self.db_path) as s:
            ra = s.get_photo(pa)
            rb = s.get_photo(pb)
        self._clear()
        for p, tag in ((ra, "A"), (rb, "B")):
            col = QVBoxLayout()
            col.setSpacing(6)
            t = QLabel(f"{tag} · {os.path.basename(p.get('path', ''))}")
            t.setObjectName("SectionTitle")
            col.addWidget(t)
            col.addWidget(_thumb_label(p.get("path", ""), 380, 260))
            for name, val, lvl, desc in score_breakdown(p):
                row = QHBoxLayout()
                n = QLabel(name)
                n.setFixedWidth(48)
                n.setStyleSheet(f"color:{C_MUTED};")
                v = QLabel(val)
                v.setFixedWidth(100)
                v.setStyleSheet(f"color:{_LEVEL_COLOR[lvl]};font-weight:600;")
                d = QLabel(desc)
                row.addWidget(n)
                row.addWidget(v)
                row.addWidget(d, 1)
                col.addLayout(row)
            self.hl.addLayout(col)

    def _clear(self):
        while self.hl.count():
            it = self.hl.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()


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
        self._popover = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 14, 20, 14)
        root.setSpacing(8)

        top = QHBoxLayout()
        t = QLabel("③ 人工复核")
        t.setObjectName("PageTitle")
        self.summary_lb = QLabel("")
        self.summary_lb.setStyleSheet(
            f"background:{C_OK_SOFT};border:1px solid {C_OK};"
            f"border-radius:8px;padding:6px 10px;color:#1f7a3d;")
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
        self.group_ctx_lb = QLabel("")
        self.group_ctx_lb.setStyleSheet(
            f"background:{C_PANEL};border:1px solid {C_BORDER};border-radius:8px;"
            f"padding:5px 10px;color:{C_TEXT};")
        lay.addWidget(self.group_ctx_lb)
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
        self.film_area.setFixedHeight(150)
        self.film_host = QWidget()
        self.film_lay = QHBoxLayout(self.film_host)
        self.film_lay.setContentsMargins(2, 2, 2, 2)
        self.film_lay.setSpacing(6)
        self.film_area.setWidget(self.film_host)
        lay.addWidget(self.film_area)

        legend = ("快捷键：0-5 标星 · P 保留 / X 排除 · A/B/C/D 选候选 · "
                  "←/→ 或 Tab 切换组 · Esc 退出复核　|　"
                  "悬停缩略图看评分，点「评分说明」看维度拆解")
        kb = QLabel(legend)
        kb.setStyleSheet(f"background:{C_PRIMARY_SOFT};border:1px solid {C_PRIMARY};"
                         f"border-radius:8px;padding:6px 10px;color:{C_TEXT};")
        kb.setWordWrap(True)
        lay.addWidget(kb)
        btns = QHBoxLayout()
        b_prev = QPushButton("← 上一组")
        b_next = QPushButton("跳过 → 下一组")
        b_undo = QPushButton("↩ 撤销")
        b_cmp = QPushButton("A/B 对比")
        b_cmp.setObjectName("Ghost")
        b_burst = QPushButton("本组仅留最佳帧")
        b_burst.setObjectName("Danger")
        b_done = QPushButton("完成甄选 → 确认")
        b_done.setObjectName("Primary")
        b_prev.clicked.connect(lambda: self._step(-1))
        b_next.clicked.connect(lambda: self._step(1))
        b_undo.clicked.connect(self._undo)
        b_cmp.clicked.connect(self._open_compare)
        b_burst.clicked.connect(self._keep_only_best)
        b_done.clicked.connect(lambda: self.app.goto("export"))
        btns.addWidget(b_prev)
        btns.addWidget(b_next)
        btns.addWidget(b_undo)
        btns.addWidget(b_cmp)
        btns.addWidget(b_burst)
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
        self.ov_losers = QCheckBox("显示落败近似帧")
        self.ov_losers.setChecked(False)
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
        frow.addWidget(self.ov_losers)
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
        self.ov_losers.toggled.connect(self._refresh_overview)
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

        # 近似重复落败帧：默认收起的可折叠组（可找回，不混在废片里）
        self.losers_box = Collapsible("近似重复落败帧（近重复 · 可找回，默认收起）")
        lay.addWidget(self.losers_box)
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
        if self._popover is not None:
            self._popover.close()
            self._popover = None
        if not self.groups:
            self.prog_lb.setText("🎉 没有需要人工甄选的组——所有相似组都已自动推荐最佳帧。")
            self.group_ctx_lb.setText("")
            return
        self._load_group()
        g = self.groups[self.idx]
        self.prog_lb.setText(
            f"待甄选组 {self.idx + 1}/{len(self.groups)} · 组 {g['id']} "
            f"共 {g.get('size', 0)} 张，候选 {len(self.cands)} 张")
        # 组上下文（连拍保护信息）
        with PhotoStore(self.app.db_path) as s:
            members = s.group_members(g["id"])
            best = s.get_group(g["id"]).get("best_path")
        kept = sum(1 for m in members
                   if (m.get("star") or 0) >= 4 or m.get("label") == "P")
        best_name = os.path.basename(best) if best else "（未推荐）"
        self.group_ctx_lb.setText(
            f"本组 {len(members)} 张　·　推荐最佳帧：{best_name}　·　已保留 {kept} 张")
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
                    thumb = _thumb_label(c["path"], 300, 200)
                    thumb.setToolTip(explain_html(c))
                    col.addWidget(thumb)
                    # 徽章行：候选标记 + 人脸/闭眼/近似重复
                    chip_row = QHBoxLayout()
                    chip_row.setSpacing(4)
                    chip_row.addWidget(_chip(f"{tag} · 候选", C_PRIMARY, "#FFFFFF"))
                    for (bt, bb, bf) in face_badges(c):
                        chip_row.addWidget(_chip(bt, bb, bf))
                    chip_row.addStretch(1)
                    col.addLayout(chip_row)
                    cap = QLabel(_meta_line(c) + "　" + _badge(c))
                    cap.setStyleSheet(f"color:{C_MUTED};font-size:12px;")
                    cap.setWordWrap(True)
                    col.addWidget(cap)
                    pb = QPushButton("选此张（★5+P）")
                    pb.clicked.connect(lambda _, x=i: self._pick_candidate(x))
                    col.addWidget(pb)
                    info = QPushButton("ⓘ 评分说明")
                    info.setObjectName("Ghost")
                    info.clicked.connect(lambda _, ph=c["path"]: self._show_popover(ph, info))
                    col.addWidget(info)
                    row_lay.addLayout(col)
                self.compare_lay.addLayout(row_lay)
        else:
            self.compare_lay.addWidget(QLabel("该组没有可用候选。"))
        # 胶片条
        for m in members:
            card = QFrame()
            card.setFixedWidth(120)
            card.setStyleSheet(
                f"background:{C_CARD};border:2px solid {_fs_color(m)};border-radius:8px;")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(4, 4, 4, 4)
            cl.setSpacing(2)
            th = _thumb_label(m["path"], 108, 72)
            th.setToolTip(explain_html(m))
            cl.addWidget(th)
            fn = QLabel(os.path.basename(m["path"])[:16])
            fn.setStyleSheet(f"color:{C_MUTED};font-size:10px;")
            fn.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cl.addWidget(fn)
            bchips = face_badges(m)
            if bchips:
                br = QHBoxLayout()
                br.setSpacing(2)
                for (bt, bb, bf) in bchips:
                    br.addWidget(_chip(bt, bb, bf))
                br.addStretch(1)
                cl.addLayout(br)
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
        # 在文本框/下拉框/数字框中打字时不触发快捷键
        fw = self.focusWidget()
        if isinstance(fw, (QLineEdit, QSpinBox, QComboBox)):
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
            self.app.goto("import")   # 退出复核，回到导入
        else:
            super().keyPressEvent(e)

    def _star_current(self, star: int):
        if self.cands:
            self._set_star(self.cands[0]["path"], star)

    def _pick_current(self, label: str):
        if self.cands:
            self._set_label(self.cands[0]["path"], label)
            self._step(1)

    def _show_popover(self, path: str, btn: QPushButton):
        """点击「评分说明」：弹出可解释评分面板（点击外部自动关闭）。"""
        if self._popover is not None:
            self._popover.close()
            self._popover = None
        with PhotoStore(self.app.db_path) as s:
            p = s.get_photo(path)
        if not p:
            return
        pop = ScorePopover(p)
        pop.show()
        pop.move(btn.mapToGlobal(btn.rect().bottomLeft()))
        self._popover = pop

    def _keep_only_best(self):
        """连拍保护：仅保留组内推荐最佳帧，其余排除（需二次确认）。"""
        if not self.groups:
            return
        g = self.groups[self.idx]
        with PhotoStore(self.app.db_path) as s:
            members = s.group_members(g["id"])
            best = s.get_group(g["id"]).get("best_path")
        if not best:
            QMessageBox.information(self, "提示", "该组暂无推荐最佳帧，无法执行此操作。")
            return
        others = [m for m in members if m["path"] != best]
        if not others:
            QMessageBox.information(self, "提示", "该组仅最佳帧一张，无需操作。")
            return
        ans = QMessageBox.question(
            self, "保护连拍",
            f"本组共 {len(members)} 张，将排除其余 {len(others)} 张、仅保留最佳帧：\n"
            f"{os.path.basename(best)}\n\n这些照片将被标记为「排除(X)」，"
            f"可通过撤销或重新分析找回。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ans != QMessageBox.StandardButton.Yes:
            return
        with PhotoStore(self.app.db_path) as s:
            for m in others:
                s.set_pick(m["path"], "X")
        self.app.status(f"已保留最佳帧，排除 {len(others)} 张连拍近似帧。")
        self._show_queue()

    def _open_compare(self):
        """A/B 双图对比对话框。"""
        if not self.groups:
            QMessageBox.information(self, "提示", "当前没有可对比的组。")
            return
        g = self.groups[self.idx]
        with PhotoStore(self.app.db_path) as s:
            members = s.group_members(g["id"])
        if len(members) < 2:
            QMessageBox.information(self, "提示", "该组成员不足 2 张，无法对比。")
            return
        dlg = CompareDialog(self.app.db_path, members, self)
        dlg.exec()

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
        show_losers = self.ov_losers.isChecked()
        only_best = self.ov_best.isChecked()
        search = self.ov_search.text().strip().lower()

        def is_loser(p):
            return bool(p.get("is_similar_loser")) and not p.get("is_waste")

        def keep(p):
            if sel_scene != "全部" and (p.get("scene") or "其他") != sel_scene:
                return False
            if (p.get("star") or 0) < star_min:
                return False
            if p.get("is_waste") and not show_waste:
                return False
            if is_loser(p) and not show_losers:
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
            th.setToolTip(explain_html(p))
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
        if filtered:
            self.ov_table.resizeRowsToContents()

        # 近似重复落败帧：默认收起的可折叠组（可找回）
        self.losers_box.clear_body()
        losers = [p for p in photos if is_loser(p)]
        if losers:
            grid = QWidget()
            gl = QGridLayout(grid)
            gl.setSpacing(8)
            cols = 6
            for i, p in enumerate(losers):
                cell = QWidget()
                cl = QVBoxLayout(cell)
                cl.setSpacing(3)
                th = _thumb_label(p["path"], 150, 100)
                th.setToolTip(explain_html(p))
                cl.addWidget(th)
                fn = QLabel(os.path.basename(p["path"])[:18])
                fn.setStyleSheet(f"color:{C_MUTED};font-size:10px;")
                fn.setAlignment(Qt.AlignmentFlag.AlignCenter)
                cl.addWidget(fn)
                row2 = QHBoxLayout()
                bk = QPushButton("找回")
                bk.setFixedHeight(22)
                bk.clicked.connect(lambda _, pp=p["path"]: self._recover_loser(pp))
                row2.addWidget(bk)
                cl.addLayout(row2)
                gl.addWidget(cell, i // cols, i % cols)
            self.losers_box.addWidget(grid)

    def _recover_loser(self, path: str):
        """找回近似重复落败帧：标记保留，使其进入导出清单。"""
        with PhotoStore(self.app.db_path) as s:
            s.set_pick(path, "P")
        self.app.status(f"已找回近似帧：{os.path.basename(path)}")
        self._refresh_overview()

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

        self.losers_box = Collapsible("近似重复落败帧（近重复 · 默认收起，可找回）")
        lay.addWidget(self.losers_box)

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

        # 近似重复落败帧：默认收起的可折叠组，便于找回近重复
        losers = [p for p in self.photos
                  if p.get("is_similar_loser") and not p.get("is_waste")]
        self.losers_box.clear_body()
        if losers:
            grid = QWidget()
            gl = QGridLayout(grid)
            gl.setSpacing(8)
            cols = 4
            for i, p in enumerate(losers):
                cell = QWidget()
                cl = QVBoxLayout(cell)
                cl.setSpacing(3)
                th = _thumb_label(p["path"], 150, 100)
                th.setToolTip(explain_html(p))
                cl.addWidget(th)
                fn = QLabel(os.path.basename(p["path"])[:18])
                fn.setStyleSheet(f"color:{C_MUTED};font-size:10px;")
                fn.setAlignment(Qt.AlignmentFlag.AlignCenter)
                cl.addWidget(fn)
                row2 = QHBoxLayout()
                bk = QPushButton("找回")
                bk.setFixedHeight(22)
                bk.clicked.connect(lambda _, pp=p["path"]: self._recover_export(pp))
                row2.addWidget(bk)
                cl.addLayout(row2)
                gl.addWidget(cell, i // cols, i % cols)
            self.losers_box.addWidget(grid)

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

    def _recover_export(self, path: str):
        """找回近似重复落败帧：标记保留，使其进入导出清单。"""
        with PhotoStore(self.app.db_path) as s:
            s.set_pick(path, "P")
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
        # 加载浅色主题样式表；失败则回退到内联浅色 QSS
        try:
            with open(os.path.join(_HERE, "styles.qss"), encoding="utf-8") as _f:
                self.setStyleSheet(_f.read())
        except Exception:
            self.setStyleSheet(FALLBACK_QSS)
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
        self.nav.setObjectName("Nav")
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
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
