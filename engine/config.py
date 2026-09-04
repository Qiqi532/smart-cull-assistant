# -*- coding: utf-8 -*-
"""
config.py —— 全项目可调参数唯一来源（MVP 配置集中化）

设计目标：
    1. 所有可调阈值 / 权重 / 模型名 / 分析尺寸集中在这里，带默认值与中文注释；
    2. engine 各模块只从本文件读取参数，不再散落硬编码常量；
    3. app（Streamlit 侧栏滑块）也读本文件，做到“改配置即生效、界面与引擎口径一致”。

修改方式：
    直接修改下方值即可；各模块启动时读取最新值。分析进行中修改不会影响
    正在进行的任务（下一次分析生效）。
"""
from __future__ import annotations

import os

# ===========================================================================
# 一、路径与目录（项目内所有缓存/数据，均不落 C 盘）
# ===========================================================================
# 项目根目录（photo-cull-demo/）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = os.path.join(PROJECT_ROOT, "data")          # 数据目录（测试图 / 数据库）
DEFAULT_DB = os.path.join(DATA_DIR, "cull.db")         # 默认 SQLite 索引库
MODELS_DIR = os.path.join(PROJECT_ROOT, "models")      # 模型权重目录（小权重随项目分发）
THUMB_DIR_NAME = ".thumbs"                             # 缩略图缓存目录名（扫描时自动跳过点开头目录）
LOG_FILE = os.path.join(PROJECT_ROOT, "smart_cull.log")  # 统一日志文件

# ===========================================================================
# 二、图像格式与加载
# ===========================================================================
# 大众格式（默认处理）；RAW 仅在检测到扩展名且已安装 rawpy 时启用
JPEG_PNG_EXTS = {".jpg", ".jpeg", ".png"}
RAW_EXTS = {".cr2", ".cr3", ".nef", ".arw", ".raf", ".orf", ".rw2", ".dng", ".pef", ".sr2"}

LOAD_MAX_SIZE = 512        # 分析用图最大边长（质量/人脸/场景共用，避免反复解码）
PHASH_SIZE = 256           # pHash 计算用图最大边长
THUMB_DEFAULT_SIZE = 320   # 缩略图默认尺寸（app 展示）
THUMB_QUALITY = 88         # 缩略图 JPEG 质量
THUMB_MAX_SIZE = 1000      # 大图对比展示尺寸（app 复核页）

# ===========================================================================
# 三、质量检测（quality.py）
# ===========================================================================
BLUR_WASTE_THRESHOLD = 60.0    # 拉普拉斯方差 < 60 视为严重模糊（废片）
EXPO_WASTE_RATIO = 0.5         # 过曝/欠曝像素占比 > 0.5 视为严重
BLUR_ANALYZE_SIZE = 512        # 拉普拉斯方差统一分析尺寸（保证可比）
BRISQUE_ANALYZE_SIZE = 512     # BRISQUE 输入尺寸
BRISQUE_SATURATED = 80.0       # BRISQUE ≥80 高度怀疑非自然内容（插画/截图）→ 中性化保护
BRISQUE_WASTE_THRESHOLD = 50.0 # BRISQUE > 50 视为严重失真（仅作评分参考，不作废片触发源）

# ===========================================================================
# 四、相似聚类（similarity.py）
# ===========================================================================
BURST_INTERVAL_MS = 1500.0     # 连拍时间间隔阈值：相邻拍摄时间 < 1500ms 归入同一连拍组
PHASH_THRESHOLD = 12           # pHash 汉明距离 < 12 视为相似
PHASH_HASH_SIZE = 8            # pHash 位数（8x8=64 位）

# ===========================================================================
# 五、人脸与闭眼（faces.py）
# ===========================================================================
EAR_CLOSED_THRESHOLD = 0.20    # EAR < 0.20 视为闭眼（明显闭眼）
FACE_NEUTRAL_N = 0.5           # 检测不到人脸时 face 维度取中性值（不做闭眼硬判）
# 闭眼 ViT 分类器（dima806，Apache-2.0，输入为眼睛区域裁剪图）
EYE_MODEL_NAME = "dima806/closed_eyes_image_detection"
EYE_MODEL_CONF = 0.60          # 分类器闭眼置信度阈值（高于则判闭眼）
EYE_CROP_CONTEXT = 1.2         # 眼睛裁剪上下文放大系数
EYE_MODEL_EAR_LO = 0.15        # 分类器触发区间下限（明显睁眼 EAR≥0.33 不跑分类器）
EYE_MODEL_EAR_HI = 0.33        # 分类器触发区间上限（明显闭眼 EAR<0.15 不跑分类器）

# ===========================================================================
# 六、美学与场景（aesthetics.py / scene.py）
# ===========================================================================
# CLIP 美学提示词（仅当 LAION 美学头缺失/加载失败时作为降级方案）
AESTHETIC_GOOD_PROMPTS = [
    "a beautiful professional photo, sharp, well composed, great lighting",
    "a high-quality award-winning photograph",
]
AESTHETIC_BAD_PROMPTS = [
    "a blurry amateur snapshot",
    "a poorly composed ugly photo",
]
# 场景候选（取空格前单词作为场景名）
SCENES = [
    "人像 portrait",
    "风光 landscape",
    "建筑/城市 architecture",
    "街拍/纪实 street",
    "宠物 pet",
    "静物/美食 still life",
    "其他 other",
]
SCENE_CONF_THRESHOLD = 0.6     # 场景置信度 < 0.6 归入“其他”兜底
CLIP_MODEL_NAME = "openai/clip-vit-base-patch32"   # 美学 + 场景共用模型
# LAION-Aesthetics 线性头（基于 openai/clip-vit-base-patch32 图像嵌入，约 3KB，随项目分发）
AESTHETIC_HEAD_PATH = os.path.join(MODELS_DIR, "sa_0_4_vit_b_32_linear.pth")

# ===========================================================================
# 七、评分与甄选（scorer.py）
# ===========================================================================
# 三套场景预设：权重 (清晰, 曝光, 美学, 人脸) 与是否启用闭眼硬判
SCENE_PRESETS = {
    "人像": {"w": (0.25, 0.20, 0.25, 0.30), "check_eye": True, "label": "人像"},
    "风光": {"w": (0.35, 0.30, 0.35, 0.00), "check_eye": False, "label": "风光"},
    "其他": {"w": (0.30, 0.20, 0.30, 0.20), "check_eye": True, "label": "其他"},
}
BLUR_WASTE = BLUR_WASTE_THRESHOLD   # 严重模糊阈值（与质量检测同源）
EXPO_WASTE = EXPO_WASTE_RATIO       # 严重过曝/欠曝占比
EAR_WASTE = EAR_CLOSED_THRESHOLD    # 闭眼 EAR 阈值（与 faces 同源）
BRISQUE_WASTE = BRISQUE_WASTE_THRESHOLD  # BRISQUE 严重失真参考阈值
SCORE_GAP = 3.0                     # Top1-Top2 综合分差 < 3 → 无明确胜者 → 待甄选
SCENE_CONF_LOW = SCENE_CONF_THRESHOLD  # 场景置信度阈值（< 则待甄选）
DIM_GAP = 0.05                      # 维度冲突判定：两候选维度差距 < 0.05 且互有胜负
MAX_CANDIDATES = 5                  # 待甄选候选最多 5 张
MIN_CANDIDATES = 2                  # 待甄选候选最少 2 张
FACE_NEUTRAL = FACE_NEUTRAL_N       # 无脸时 face 维度中性值

# ===========================================================================
# 八、流水线（pipeline.py）
# ===========================================================================
ANALYZE_SIZE = LOAD_MAX_SIZE   # 分析用图尺寸（质量/人脸）
CLIP_BATCH = 16                # CLIP 批量推理大小（GPU 友好）
CLIP_LOAD_SIZE = 256           # CLIP 阶段重新解码用图边长（CLIP 内部缩到 224，256 足够）
QUALITY_WORKERS = 4            # 质量检测线程池并行数（纯 cv2 计算，GIL 释放，可并行）
STAGE1_WRITE_BATCH = 1         # 阶段一结果逐张写库（WAL 下开销极小，保证断电续跑精度）

# ===========================================================================
# 九、导出
# ===========================================================================
EXPORT_SUBDIR = "photos"       # 导出时复制文件的子目录名
EXPORT_CSV_NAME = "smart_cull_export.csv"  # 导出 CSV 清单文件名
EXPORT_SELECT_MIN_STAR = 4     # “保留清单”默认星级阈值（★≥4 或 P 视为选中）

# ===========================================================================
# 十、其他
# ===========================================================================
# 分析阶段名（进度回调与断点续跑状态共用）
PHASES = ["扫描", "读取元数据", "质量与哈希", "美学与场景", "相似聚类", "评分与甄选"]
