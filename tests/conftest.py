# -*- coding: utf-8 -*-
"""tests/conftest.py —— 让 pytest 直接 import pipeline/brand_analyzer 等模块。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPE = os.path.join(ROOT, "pipeline")
for p in (ROOT, PIPE):
    if p not in sys.path:
        sys.path.insert(0, p)
