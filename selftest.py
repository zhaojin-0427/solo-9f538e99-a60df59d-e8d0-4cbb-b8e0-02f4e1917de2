#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键自测：冲突有解、无解两种情形及其余约束用例。

用法（无需安装 pytest，标准库即可）：
    python selftest.py
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    loader = unittest.TestLoader()
    suite = loader.discover(str(ROOT / "tests"), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)

    print("\n================ 关键情形说明 ================")
    print("有解：提交 img1/img2 的正确新对位 (440,170)-(40,170)")
    print("      -> 采用 DW-06(已复核)，撤下 DW-02、DW-03，")
    print("         LF-03 -> (960,200)，LF-04 -> (1120,90)。")
    print("无解：提交 img0/img1 的 (470,150)-(20,150)")
    print("      -> 与已复核 DW-01 冲突，任何 <=2 条撤法均不可行，")
    print("         原图与对位保持不变（仅写一条 no_solution 审计记录）。")
    print("============================================\n")

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
