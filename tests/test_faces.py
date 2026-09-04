# -*- coding: utf-8 -*-
"""faces.py 单测：EAR + 分类器融合规则、边界区间触发逻辑（不跑真实模型）。"""
from __future__ import annotations

import numpy as np
from PIL import Image

import engine.faces as faces


class _FakeMesh:
    """伪造 mediapipe FaceMesh：返回 478 个伪关键点，触发分类器分支。"""

    def __init__(self, **kw):
        pass

    def process(self, arr):
        class LM:
            x = 0.5
            y = 0.3
        class FLM:
            landmark = [LM() for _ in range(478)]
        class Res:
            multi_face_landmarks = [FLM()]
        return Res()


def _fake_mesh(monkeypatch):
    import mediapipe.python.solutions.face_mesh as _fm
    monkeypatch.setattr(_fm, "FaceMesh", _FakeMesh)


def _rgb():
    return np.zeros((32, 32, 3), dtype=np.uint8)


def _pil():
    return Image.new("RGB", (32, 32), (100, 100, 100))


def test_ear_open_above_hi_skips_classifier(monkeypatch):
    """明显睁眼（EAR 高于上界）时不应调用分类器。"""
    calls = {"n": 0}
    monkeypatch.setattr(faces, "detect_face_ear", lambda rgb, thr: {
        "is_face": True, "num_faces": 1, "ear": 0.5,
        "eyes_closed": False, "error": None})
    monkeypatch.setattr(faces, "eye_close_probability",
                        lambda *a, **k: calls.__setitem__("n", calls["n"] + 1) or 0.0)
    r = faces.detect_face_and_eyes(_rgb())
    assert calls["n"] == 0
    assert r["eye_close_prob"] is None
    assert r["eyes_closed"] is False


def test_ear_closed_below_lo_skips_classifier(monkeypatch):
    """明显闭眼（EAR 低于下界）直接判定闭眼，不跑分类器。"""
    calls = {"n": 0}
    monkeypatch.setattr(faces, "detect_face_ear", lambda rgb, thr: {
        "is_face": True, "num_faces": 1, "ear": 0.05,
        "eyes_closed": True, "error": None})
    monkeypatch.setattr(faces, "eye_close_probability",
                        lambda *a, **k: calls.__setitem__("n", calls["n"] + 1) or 1.0)
    r = faces.detect_face_and_eyes(_rgb())
    assert calls["n"] == 0
    assert r["eyes_closed"] is True


def test_boundary_interval_triggers_classifier(monkeypatch):
    """EAR 落在边界区间才触发分类器，且分类器高置信度判闭眼。"""
    calls = {"n": 0}
    _fake_mesh(monkeypatch)
    monkeypatch.setattr(faces, "detect_face_ear", lambda rgb, thr: {
        "is_face": True, "num_faces": 1, "ear": 0.25,   # 落在 [0.15, 0.33]
        "eyes_closed": False, "error": None})
    monkeypatch.setattr(faces, "eye_close_probability",
                        lambda *a, **k: calls.__setitem__("n", calls["n"] + 1) or 0.9)
    r = faces.detect_face_and_eyes(_rgb(), pil_img=_pil())
    assert calls["n"] == 1
    assert r["eye_close_prob"] == 0.9
    assert r["eyes_closed"] is True


def test_boundary_interval_classifier_low_conf(monkeypatch):
    """边界区间分类器低置信度 → 不误判闭眼。"""
    _fake_mesh(monkeypatch)
    monkeypatch.setattr(faces, "detect_face_ear", lambda rgb, thr: {
        "is_face": True, "num_faces": 1, "ear": 0.25,
        "eyes_closed": False, "error": None})
    monkeypatch.setattr(faces, "eye_close_probability", lambda *a, **k: 0.2)
    r = faces.detect_face_and_eyes(_rgb(), pil_img=_pil())
    assert r["eyes_closed"] is False


def test_no_face_neutral():
    """无脸时不判闭眼，eye_close_prob 为 None。"""
    r = faces.detect_face_and_eyes(_rgb())
    assert r["is_face"] is False
    assert r["eyes_closed"] is False
    assert r["eye_close_prob"] is None
