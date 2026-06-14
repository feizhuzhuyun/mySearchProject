"""
特征提取器实现 — 阶段 3 填充真实模型（CLIP / DINOv2 等）。
当前为占位文件，删除不影响 app 核心功能。
"""
from models import register
from models.base import BaseFeatureExtractor

# ── 阶段 3 实现示例 ────────────────────────────────────────────────
# try:
#     import open_clip
#     import torch
#     HAS_CLIP = True
# except ImportError:
#     HAS_CLIP = False
#
# if HAS_CLIP:
#     @register("feature_extractors")
#     class CLIPExtractor(BaseFeatureExtractor):
#         name = "CLIP ViT-B/32"
#         dim = 512
#         priority = 1
#
#         def __init__(self, device="cpu"):
#             self._device = device
#             self._model, _, self._preprocess = open_clip.create_model_and_transforms(
#                 "ViT-B-32", pretrained="laion2b_s34b_b79k"
#             )
#             self._model = self._model.to(device).eval()
#
#         def extract_batch(self, paths):
#             ...
#         def extract_single(self, path):
#             ...
