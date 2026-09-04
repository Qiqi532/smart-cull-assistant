# -*- coding: utf-8 -*-
"""
quality.py —— 模糊、曝光（过曝/欠曝）、噪点检测

算法：
    1. 模糊（启发式）：灰度图拉普拉斯方差（Laplacian variance），统一缩放 512x512 保证可比。
       经验值：风景/静物 >150 清晰，<60 明显模糊（阈值可按素材标定）。
    2. 曝光：灰度直方图两端像素占比。over = hist[245:]/total（高光溢出），
       under = hist[:10]/total（暗部死黑）。over>0.5 或 under>0.5 视为严重过曝/欠曝。
    3. 噪点：高频分量占比近似估计（可选用）。
    4. 【模型升级 v2.2】BRISQUE 无参考质量分：LIVE 数据集（人眼标注失真图）训练的标准
       无参考图像质量回归器（0-100，越低越好）。对模糊/噪声/JPEG 压缩/曝光失真均敏感，
       可替代/增强启发式模糊判定，避免“平滑墙面被误判模糊”的纹理偏置。

独立命令行调试：python -m engine.quality <图片路径>
"""
from __future__ import annotations

import cv2
import numpy as np

from . import config
from .loader import cv_imread, load_image_rgb_array
from .log import get_logger

# 阈值统一来自 engine/config.py（改配置即生效，界面与引擎口径一致）
BLUR_WASTE_THRESHOLD = config.BLUR_WASTE_THRESHOLD   # 拉普拉斯方差 < 60 视为严重模糊
EXPO_WASTE_RATIO = config.EXPO_WASTE_RATIO           # 过曝/欠曝占比 > 0.5 视为严重
BLUR_ANALYZE_SIZE = config.BLUR_ANALYZE_SIZE         # 拉普拉斯方差统一分析尺寸
BRISQUE_WASTE_THRESHOLD = config.BRISQUE_WASTE_THRESHOLD  # BRISQUE > 50 视为严重失真（LIVE 训练模型）
BRISQUE_ANALYZE_SIZE = config.BRISQUE_ANALYZE_SIZE   # BRISQUE 输入尺寸（越大越准，512 足够）
BRISQUE_SATURATED = config.BRISQUE_SATURATED         # BRISQUE ≥80 饱和中性化保护阈值

_log = get_logger("quality")


def blur_score_from_gray(gray: np.ndarray) -> float:
    """由灰度图计算拉普拉斯方差（清晰度分数），数值越高越清晰。"""
    if gray is None or gray.size == 0:
        return 0.0
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, (BLUR_ANALYZE_SIZE, BLUR_ANALYZE_SIZE))
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def blur_score(path: str) -> float:
    """按路径计算模糊分数（拉普拉斯方差）。失败返回 0.0（视为最模糊）。"""
    gray = cv_imread(path, cv2.IMREAD_GRAYSCALE)
    return blur_score_from_gray(gray)


def exposure_ratio_from_gray(gray: np.ndarray) -> tuple[float, float]:
    """由灰度图计算 (over, under) 占比。"""
    if gray is None or gray.size == 0:
        return (0.0, 0.0)
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    hist = cv2.calcHist([gray], [0], None, [256], [0, 256]).flatten()
    total = float(gray.size)
    if total <= 0:
        return (0.0, 0.0)
    over = float(hist[245:].sum()) / total   # 高光溢出占比
    under = float(hist[:10].sum()) / total   # 暗部死黑占比
    return over, under


def exposure_ratio(path: str) -> tuple[float, float]:
    """按路径计算 (over, under)。"""
    gray = cv_imread(path, cv2.IMREAD_GRAYSCALE)
    return exposure_ratio_from_gray(gray)


def noise_estimate_from_gray(gray: np.ndarray) -> float:
    """噪点近似：高频分量占比（拉普拉斯绝对值均值 / 255）。仅供参考，不用于废片判定。"""
    if gray is None or gray.size == 0:
        return 0.0
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    return float(np.abs(lap).mean() / 255.0)


def analyze_image_array(rgb: np.ndarray) -> dict:
    """由 RGB 数组一次算出 blur_score / over / under / noise。

    供批量分析链路使用（避免同一张图重复读盘解码）。
    """
    if rgb is None or rgb.size == 0:
        return {"blur_score": 0.0, "over": 0.0, "under": 0.0, "noise": 0.0}
    # RGB -> 灰度
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    return {
        "blur_score": blur_score_from_gray(gray),
        "over": exposure_ratio_from_gray(gray)[0],
        "under": exposure_ratio_from_gray(gray)[1],
        "noise": noise_estimate_from_gray(gray),
    }


def analyze_path(path: str) -> dict:
    """按路径分析整张图的质量指标。"""
    rgb = load_image_rgb_array(path)
    return analyze_image_array(rgb)


# ---------------------------------------------------------------------------
# 【模型升级 v2.2】BRISQUE 无参考质量分（LIVE 数据集训练的现成模型）
# ---------------------------------------------------------------------------
_brisque = None
_brisque_device = None


def get_brisque():
    """懒加载 BRISQUE 指标（pyiqa，权重缓存于项目内 .torch_cache）。"""
    global _brisque, _brisque_device
    if _brisque is not None:
        return _brisque
    import torch
    import pyiqa
    _brisque_device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    _brisque = pyiqa.create_metric("brisque", device=_brisque_device).eval()
    return _brisque


def brisque_score_array(rgb: np.ndarray, max_size: int = BRISQUE_ANALYZE_SIZE) -> float | None:
    """由 RGB 数组计算 BRISQUE 分（0-100，越低越好）；模型不可用时返回 None。

    注意：BRISQUE 在明亮/高饱和/纹理多的图上可能偏高，需与拉普拉斯方差互补使用。
    """
    try:
        if rgb is None or rgb.size == 0:
            return None
        import torch
        m = get_brisque()
        img = cv2.resize(rgb, (max_size, max_size), interpolation=cv2.INTER_AREA)
        t = torch.from_numpy(np.ascontiguousarray(img)).permute(2, 0, 1).unsqueeze(0).float() / 255.0
        t = t.to(_brisque_device)
        with torch.no_grad():
            s = m(t)
        v = float(s[0].item())
        return max(0.0, min(100.0, v))
    except Exception as e:
        _log.warning("BRISQUE 计算失败（降级启发式）：%s", e)
        return None


def quality_model_name() -> str:
    """当前生效的质量模型名（供分析汇总展示/版本失效）。"""
    return "brisque(live)"


# ---------------------------------------------------------------------------
# 命令行调试入口
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    for p in sys.argv[1:]:
        r = analyze_path(p)
        over, under = r["over"], r["under"]
        verdict = "清晰" if r["blur_score"] >= 150 else ("模糊" if r["blur_score"] < BLUR_WASTE_THRESHOLD else "一般")
        if over > EXPO_WASTE_RATIO:
            verdict += "+严重过曝"
        elif under > EXPO_WASTE_RATIO:
            verdict += "+严重欠曝"
        print(f"{p}\n  blur={r['blur_score']:.1f} over={over:.3f} under={under:.3f} noise={r['noise']:.3f} -> {verdict}")
