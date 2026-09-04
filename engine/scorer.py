# -*- coding: utf-8 -*-
"""
scorer.py —— 场景自适应综合评分、废片判定、最佳帧推荐与不确定候选甄选

算法（设计文档 4.4.8 / 4.4.9）：
    1. 三套场景预设（人像/风光/其他），权重 = 清晰/曝光/美学/人脸：
         人像 (0.25, 0.20, 0.25, 0.30)，启用闭眼硬判
         风光 (0.35, 0.30, 0.35, 0.00)，不启用闭眼
         其他 (0.30, 0.20, 0.30, 0.20)，检测到人脸才启用 face 维度
    2. 综合分 = 100 * Σ(权重 * 归一化子分)，各子分归一化到 [0,1]。
    3. 废片硬性规则：严重模糊(blur<60)、严重过曝/欠曝(over|under>0.5)、
       高度重复、人像闭眼(EAR<0.20)。
    4. 最佳帧 / 不确定甄选：
         规则1：Top1-Top2 综合分差 < 3 → 无明确胜者 → uncertain
         规则2：多维度互有胜负（帕累托冲突）→ uncertain
         规则3：场景置信度 < 0.6 → uncertain
         明确时推荐 Top1（自动打星 5），次高分 Top2 打星 4；
         uncertain 时甄选 2~5 张候选进入待甄选模式。

独立命令行调试：python -m engine.scorer
"""
from __future__ import annotations

from . import config

# ---------------------------------------------------------------------------
# 场景预设（设计文档表 7；权重统一来自 engine/config.py）
# ---------------------------------------------------------------------------
PRESETS = config.SCENE_PRESETS

# 判定阈值统一来自 engine/config.py（与 quality / faces 同源，口径一致）
BLUR_WASTE = config.BLUR_WASTE          # 拉普拉斯方差 < 60 严重模糊
EXPO_WASTE = config.EXPO_WASTE          # 过曝/欠曝占比 > 0.5 严重
EAR_WASTE = config.EAR_WASTE            # 闭眼阈值（EAR）
BRISQUE_WASTE = config.BRISQUE_WASTE    # BRISQUE > 50 严重失真（LIVE 训练模型，越低越好）
BRISQUE_SATURATED = config.BRISQUE_SATURATED  # BRISQUE ≥80 饱和中性化保护
SCORE_GAP = config.SCORE_GAP            # Top1-Top2 综合分差阈值（<3 视为无明确胜者）
SCENE_CONF_LOW = config.SCENE_CONF_LOW  # 场景置信度阈值
DIM_GAP = config.DIM_GAP                # 维度冲突判定的差距阈值
MAX_CANDIDATES = config.MAX_CANDIDATES  # 甄选候选最多 5 张
FACE_NEUTRAL = config.FACE_NEUTRAL      # 无脸时 face 维度中性值

DIM_KEYS = ["blur_n", "aes_n", "face_n"]   # 维度冲突比较的子维度


# ---------------------------------------------------------------------------
# 归一化
# ---------------------------------------------------------------------------
def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def norm_blur(blur_score: float) -> float:
    """清晰度归一化：拉普拉斯方差 200 视为满分，线性映射到 [0,1]。"""
    return _clip(blur_score / 200.0)


def norm_quality(brisque) -> float:
    """BRISQUE 质量归一化：越低越好，0 分满分，100 分最低。

    【防误判保护】BRISQUE 在 ≥80 时高度怀疑为“非自然照片内容”（扁平插画/截图/极暗
    高光裁剪等），此时模型不可信 → 返回中性 0.5，避免把清晰扁平图误判为“模糊”。
    """
    if brisque is None:
        return 0.5
    if brisque >= BRISQUE_SATURATED:
        return 0.5
    return 1.0 - _clip(brisque / 100.0)


def norm_expo(over: float, under: float) -> float:
    """曝光质量归一化：过曝/欠曝占比越小越接近 1。"""
    return 1.0 - _clip(over + under)


def norm_aes(aesthetic: float) -> float:
    """美学分归一化：0-100 映射到 [0,1]。"""
    return _clip(aesthetic / 100.0)


def norm_face(ear, is_face: bool) -> float:
    """人脸质量归一化：有脸时用 EAR（典型睁眼 ~0.30），无脸时取中性 0.5。"""
    if not is_face or ear is None:
        return FACE_NEUTRAL
    return _clip(ear / 0.35)


# ---------------------------------------------------------------------------
# 综合评分
# ---------------------------------------------------------------------------
def composite(blur_n, expo_n, aes_n, face_n, scene="其他", weights=None) -> float:
    """按场景预设权重计算综合分（0-100）。weights 传入 (w0,w1,w2,w3) 时覆盖预设。"""
    w = weights or PRESETS.get(scene, PRESETS["其他"])["w"]
    return 100.0 * (w[0] * blur_n + w[1] * expo_n + w[2] * aes_n + w[3] * face_n)


def analyze_photo_score(metrics: dict, scene: str = "其他", weights=None) -> dict:
    """由单张指标 dict 计算归一化子分与综合分。

    metrics 字段：blur_score, over, under, aesthetic, ear, is_face[, brisque]
    返回 dict：blur_n, expo_n, aes_n, face_n, comp_score（并保留外部传入字段）

    【模型升级 v2.2】清晰维度 = 0.5·拉普拉斯 + 0.5·BRISQUE 质量分（模型驱动的
    质量信号，降低“平滑墙面被误判模糊”的纹理偏置）；brisque 缺失时退化为纯拉普拉斯。
    """
    blur_n = norm_blur(metrics.get("blur_score", 0.0))
    brisque = metrics.get("brisque")
    if brisque is not None:
        blur_n = 0.5 * blur_n + 0.5 * norm_quality(brisque)
    expo_n = norm_expo(metrics.get("over", 0.0), metrics.get("under", 0.0))
    aes_n = norm_aes(metrics.get("aesthetic", 0.0))
    face_n = norm_face(metrics.get("ear"), bool(metrics.get("is_face", False)))
    comp = composite(blur_n, expo_n, aes_n, face_n, scene, weights)
    result = {"blur_n": blur_n, "expo_n": expo_n, "aes_n": aes_n,
              "face_n": face_n, "comp_score": comp}
    # 保留外部传入的额外字段（如 path / aesthetic / 废片原因），便于调用方追踪
    for k, v in metrics.items():
        if k not in result:
            result[k] = v
    return result


# ---------------------------------------------------------------------------
# 废片判定
# ---------------------------------------------------------------------------
def waste_reasons(scene: str, blur_score: float, over: float, under: float,
                  eyes_closed: bool, dup: bool, brisque=None) -> list[str]:
    """返回废片原因列表；空列表表示非废片。

    eyes_closed: 融合判定结果（EAR<阈值 或 闭眼分类器>阈值）。
    brisque:     仅供评分维度使用的模型质量分（0-100，越低越好）。此处不作为模糊
                 判定的独立触发源——BRISQUE 对扁平插画/截图等非自然内容会饱和误报，
                 故“模糊”废片仍以拉普拉斯方差为准，模型信号仅参与综合分（见
                 analyze_photo_score）。
    """
    reasons = []
    if blur_score < BLUR_WASTE:
        reasons.append("模糊")
    if over > EXPO_WASTE or under > EXPO_WASTE:
        reasons.append("过曝/欠曝")
    if dup:
        reasons.append("高度重复")
    if scene == "人像" and eyes_closed:
        reasons.append("闭眼")
    return reasons


def is_waste(scene: str, blur_score: float, over: float, under: float,
             eyes_closed: bool, dup: bool, brisque=None) -> bool:
    return len(waste_reasons(scene, blur_score, over, under, eyes_closed, dup, brisque)) > 0


def is_hard_waste(scene: str, blur_score: float, over: float, under: float,
                  eyes_closed: bool, brisque=None) -> bool:
    """硬性质量废片（不含'高度重复'，因为去重判定依赖组内 verdict）。"""
    return len(waste_reasons(scene, blur_score, over, under, eyes_closed, dup=False, brisque=brisque)) > 0


# ---------------------------------------------------------------------------
# 最佳帧推荐与不确定候选甄选（设计文档 4.4.9）
# ---------------------------------------------------------------------------
def _dim_conflict(a: dict, b: dict, gap: float = DIM_GAP) -> bool:
    """两个候选在清晰/美学/人脸等维度互有胜负且差距都小 → 帕累托冲突。"""
    return (all(abs(a[k] - b[k]) < gap for k in DIM_KEYS)
            and any(a[k] > b[k] for k in DIM_KEYS)
            and any(b[k] > a[k] for k in DIM_KEYS))


def judge_and_pick(scores: list[dict], scene: str = "其他",
                   conf: float = 1.0, score_gap: float | None = None,
                   scene_conf_low: float | None = None,
                   max_candidates: int | None = None) -> tuple[str, list[dict]]:
    """判断相似组是否有明确最佳帧；返回 (verdict, picks)。

    scores: 组内每张的 dict（含 comp_score, blur_n, aes_n, face_n, 以及
            外部关联字段如 path/star 等会被原样保留）
    score_gap: Top1-Top2 分差阈值（默认取 config.SCORE_GAP，可由界面滑块覆盖）
    scene_conf_low: 场景置信度阈值（默认取 config.SCENE_CONF_LOW）
    verdict: "best"（推荐 Top1，picks=[top1]）或 "uncertain"（甄选候选）
    """
    gap = score_gap if score_gap is not None else SCORE_GAP
    conf_low = scene_conf_low if scene_conf_low is not None else SCENE_CONF_LOW
    mc = max_candidates if max_candidates is not None else MAX_CANDIDATES
    if not scores:
        return "best", []
    # 候选池剔除硬性质量废片（模糊/过曝欠曝/闭眼）；全废组无推荐帧
    clean = [x for x in scores if not x.get("hard_waste")]
    if not clean:
        return "best", []
    s = sorted(clean, key=lambda x: -x["comp_score"])
    top1, top2 = s[0], s[1] if len(s) > 1 else None
    # 规则1：Top1-Top2 分差过小 → 无明确胜者
    if top2 is not None and (top1["comp_score"] - top2["comp_score"]) < gap:
        return "uncertain", s[:min(mc, len(s))]
    # 规则2：多维度互有胜负（帕累托冲突）
    if top2 is not None and _dim_conflict(top1, top2):
        return "uncertain", s[:min(mc, len(s))]
    # 规则3：场景置信度低 → 评分口径本身有歧义
    if conf < conf_low:
        return "uncertain", s[:min(mc, len(s))]
    # 明确：推荐最佳帧（自动打星 5）
    return "best", s[:1]


def pick_stars(verdict: str, picks: list[dict]) -> dict:
    """根据判定结果给出建议星级。

    best：Top1 -> 5 星（推荐帧）
    uncertain：候选第一张 -> 4 星（人工拍板前不给 5 星），其余保持 0
    返回 {path_or_key: star}
    """
    suggest = {}
    if not picks:
        return suggest
    if verdict == "best":
        key = _key(picks[0])
        suggest[key] = 5
    else:
        key = _key(picks[0])
        suggest[key] = 4
    return suggest


def _key(d: dict):
    return d.get("path") or d.get("key") or id(d)


# ---------------------------------------------------------------------------
# 命令行调试入口
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # 构造示例验证判定逻辑
    import random
    random.seed(0)
    print("场景预设：", {k: v["w"] for k, v in PRESETS.items()})
    for scene, conf in [("人像", 0.9), ("风光", 0.9), ("其他", 0.3)]:
        scores = []
        for i in range(4):
            m = {
                "path": f"img_{i}.jpg",
                "blur_score": random.uniform(80, 260),
                "over": random.uniform(0.0, 0.3),
                "under": random.uniform(0.0, 0.2),
                "aesthetic": random.uniform(40, 80),
                "ear": random.uniform(0.15, 0.35),
                "is_face": True,
            }
            scores.append(analyze_photo_score(m, scene))
        verdict, picks = judge_and_pick(scores, scene, conf)
        print(f"\n场景={scene} conf={conf} -> verdict={verdict} 候选数={len(picks)}")
        for p in picks:
            print(f"    {p['path']}: comp={p['comp_score']:.1f} "
                  f"(blur={p['blur_n']:.2f} aes={p['aes_n']:.2f} face={p['face_n']:.2f})")
