# NOTICE —— 第三方模型 / 权重来源与许可说明

本项目（光影选片助手 Smart Cull Assistant）在 Apache-2.0 许可下发布，
但**随项目使用/自动下载的第三方模型权重各有其独立许可**，使用前请阅读各自条款。

| 组件 | 用途 | 来源 | 训练数据集 | 许可 |
| --- | --- | --- | --- | --- |
| openai/clip-vit-base-patch32 | 美学评分 + 场景分类（图像编码器） | OpenAI，HuggingFace Hub | WIT-400M 等（见 OpenAI 说明） | MIT |
| LAION-Aesthetics sa_0_4_vit_b_32_linear | 美学回归线性头（约 3KB，随项目分发） | LAION-AI，HuggingFace Hub | LAION-Aesthetics 子集（用户标注打分） | Apache-2.0 |
| dima806/closed_eyes_image_detection | 闭眼检测 ViT 分类器 | dima806，HuggingFace Hub | 闭眼检测标注数据集（见该模型卡） | Apache-2.0 |
| MediaPipe Face Mesh / Face Detection | 人脸关键点（EAR 计算） | Google | Google 内部标注 | Apache-2.0 |
| pyiqa（BRISQUE 无参考质量分） | 图像质量回归 | IQA-Pytorch 项目 | LIVE / TID2013 等（人眼失真评分） | Apache-2.0 |
| rawpy（libraw 绑定） | RAW 解码（可选） | letmaik，LibRaw | — | MIT（libraw 为 LGPL/CC 双许可） |

说明：
- CLIP 与 MediaPipe 权重首次运行自动从 HuggingFace Hub 下载，缓存于项目内
  `.hf_cache` / `.torch_cache`（不落 C 盘），断网时可离线使用已缓存权重。
- LAION-Aesthetics 线性头体积小（约 3KB），随仓库一并提交，无需联网下载。
- 若你的使用场景要求更严格的权重许可合规，请自行核对上表各上游仓库的
  最新 LICENSE / 使用条款。
