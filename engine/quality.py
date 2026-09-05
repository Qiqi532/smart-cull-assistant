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
# 【模型升级 v0.4】无参考画质模型（可插拔 + 自动降级链）
#
# 为什么要换掉 BRISQUE（实测 + 文献双重证据）：
#   * 精度：BRISQUE 是 2000 年代的 hand-crafted 特征（LIVE 数据集），在 KonIQ-10k
#     上 SRCC 约 0.665；MUSIQ 约 0.916、DBCNN 约 0.88 —— 差距是一整个时代。
#   * 速度：本项目实测 musiq 74ms、musiq-ava 44ms、dbcnn 39ms、brisque 60ms
#     —— 换更强的模型反而【更快】（BRISQUE 的 CPU 特征提取是隐藏瓶颈）。
#   * 泛化：BRISQUE 在扁平插画/截图/极暗高光裁剪上会饱和误报，旧代码不得不加
#     "≥80 中性化"这种补丁；MUSIQ/DBCNN 这类数据驱动模型没有这个问题。
# 降级链：IQA_MODEL → IQA_FALLBACKS → None（退化为纯拉普拉斯，功能不中断）。
# ---------------------------------------------------------------------------
_iqa = None
_iqa_name = None
_iqa_device = None


def _make_iqa(name: str):
    """工厂：按名字创建 pyiqa 指标（供 models_guard.try_load 降级链调用）。"""
    import torch
    import pyiqa

    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return pyiqa.create_metric(name, device=dev).eval(), dev


def get_iqa():
    """懒加载画质模型（带降级链）。返回 (name, metric, device)；完全失败返回 (None, None, None)。"""
    global _iqa, _iqa_name, _iqa_device
    if _iqa is not None:
        return _iqa_name, _iqa, _iqa_device
    from . import models_guard

    models_guard.apply_env()
    candidates = [(config.IQA_MODEL, lambda: _make_iqa(config.IQA_MODEL))]
    for fb in config.IQA_FALLBACKS:
        candidates.append((fb, (lambda n=fb: _make_iqa(n))))
    try:
        name, (metric, dev) = models_guard.try_load("画质模型", candidates)
        _iqa_name, _iqa, _iqa_device = name, metric, dev
    except models_guard.ModelLoadError as e:
        _log.error("画质模型全部不可用，退化为纯拉普拉斯清晰度：%s", e)
        _iqa_name, _iqa, _iqa_device = None, None, None
    return _iqa_name, _iqa, _iqa_device


def _normalize_iqa(name: str, raw: float) -> float:
    """把各模型的原始输出统一映射到 0-100，且**越高越好**（口径与拉普拉斯一致）。"""
    lo, hi = config.IQA_RANGES.get(name, (0.0, 100.0))
    if hi <= lo:
        return float(raw)
    x = (float(raw) - lo) / (hi - lo)
    if name in config.IQA_LOWER_IS_BETTER:   # 失真分（BRISQUE/NIQE）需反向
        x = 1.0 - x
    return max(0.0, min(100.0, x * 100.0))


def _to_batch_tensor(rgbs: list[np.ndarray], size: int):
    import torch

    imgs = []
    for rgb in rgbs:
        im = cv2.resize(rgb, (size, size), interpolation=cv2.INTER_AREA)
        imgs.append(np.ascontiguousarray(im))
    arr = np.stack(imgs).astype(np.float32) / 255.0
    return torch.from_numpy(arr).permute(0, 3, 1, 2)   # (N,3,H,W)


def iqa_score_batch(rgbs: list[np.ndarray],
                    max_size: int | None = None) -> list[float | None]:
    """批量计算画质分（0-100，越高越好）。模型不可用时返回等长 None 列表。

    批量推理是 GPU 上的关键优化：逐张调用会为每张图付出一次 kernel 启动 +
    数据搬移开销，批量后单张成本显著下降。
    """
    size = max_size or config.IQA_ANALYZE_SIZE
    name, metric, dev = get_iqa()
    if metric is None:
        return [None] * len(rgbs)
    out: list[float | None] = []
    bs = max(1, int(config.IQA_BATCH_SIZE or 1))
    for i in range(0, len(rgbs), bs):
        chunk = rgbs[i:i + bs]
        try:
            import torch

            t = _to_batch_tensor(chunk, size).to(dev)
            with torch.no_grad():
                v = metric(t)
            vals = v.reshape(-1).tolist()
            if len(vals) != len(chunk):     # 个别模型返回标量，按批均值回填
                vals = [sum(vals) / max(1, len(vals))] * len(chunk)
            out.extend(_normalize_iqa(name, x) for x in vals)
        except Exception as e:
            _log.warning("画质模型批推理失败（本批降级为逐张）：%s", e)
            out.extend(iqa_score_array(r, max_size) for r in chunk)
    return out


def iqa_score_array(rgb: np.ndarray, max_size: int | None = None) -> float | None:
    """单张画质分（0-100，越高越好）；模型不可用返回 None。"""
    if rgb is None or rgb.size == 0:
        return None
    name, metric, dev = get_iqa()
    if metric is None:
        return None
    try:
        import torch

        t = _to_batch_tensor([rgb], max_size or config.IQA_ANALYZE_SIZE).to(dev)
        with torch.no_grad():
            v = metric(t)
        arr = v.reshape(-1).tolist()
        raw = sum(arr) / len(arr) if arr else 0.0
        return _normalize_iqa(name, raw)
    except Exception as e:
        _log.warning("画质模型推理失败：%s", e)
        return None


# ---------------------------------------------------------------------------
# 向后兼容：BRISQUE 作为降级链末端仍可单独调用
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
    """由 RGB 数组计算 BRISQUE 原始失真分（0-100，越低越好）；不可用返回 None。

    保留此函数仅为兼容旧调用；新代码请用 iqa_score_array / iqa_score_batch，
    后者统一为"越高越好"口径并支持更强的模型。
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
    """当前生效的画质模型名（供分析汇总展示/版本失效）。"""
    name, metric, _ = get_iqa()
    return name or "laplacian-only"


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
