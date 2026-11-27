# 壁画裂缝定位图 · 对位更新操作台

壁画复测发现局部照片错位。本项目用 **Flask + SQLite** 做一个操作页：修复师在两张
同比例、同朝向的样片上点选同一处纹样并提交新对位，系统在严格约束下求最优撤法，
更新裂缝定位总图。

## 业务规则（与实现一一对应）

- 内置 5 张同比例（480×360）、同朝向的 SVG 壁画样片，以及按旧对位排好的总图；
  台账中标出每条对位是否**已复核**、每条裂缝是否**已贴签**。
- 样片只有平移变量：样片点 `p` 的总图坐标为 `p + (tx, ty)`。
- 对位 `(a,b)` 上同一纹样的两点 `pa,pb` 给出硬约束 `tb - ta = pa - pb`。
- 提交的新对位**必须采用**（视为已复核、不可撤）。
- **基准图 `img0` 固定**，其余照片只平移。
- 求解必须同时满足：
  1. 每张图都能经保留对位**定位到基准图**（图连通性）；
  2. **保留的对位全部成立**（默认容差 2px，见 `app/seed_data.py`）；
  3. **已贴签裂缝的总图坐标照旧**——等价于把所在照片钉在当前平移上。
- 只允许撤下**未复核**的旧对位，且**最多 2 条**。
- 优选顺序：**撤下条数最少 → 移位裂缝数最少**；再相同按对位编号取确定解。
- 有解：事务内更新照片平移（总图）、撤下旧对位、把新对位记为**已复核**，
  并列出撤下对位与移位裂缝的新坐标。
- 无解：**原图与对位完全不变**（仅多一条 `no_solution` 审计记录）。

## Docker Compose 启动

```bash
docker compose up --build
# 打开 http://localhost:5000
# 若宿主机 5000 被占用： WEB_PORT=8000 docker compose up --build
```

SQLite 数据库保存在命名卷 `mural-data` 的 `/data/mural.db`，容器重启数据不丢。
首次启动自动建表并播种内置样片数据；页面右上角可随时“重置为内置示例数据”。

## 本地直接运行

```bash
python -m pip install -r requirements.txt
python wsgi.py                 # http://127.0.0.1:5000
# 或： gunicorn --bind 0.0.0.0:5000 wsgi:application
```

本地默认数据库路径为 `data/mural.db`，可用环境变量 `MURAL_DB` 覆盖。

## 自测（冲突有解 / 无解两种情形）

```bash
python selftest.py
# 或： python -m unittest discover -s tests -v
# 也兼容： pytest -q
```

共 21 个用例（纯求解器 + Flask/SQLite 接口/事务），覆盖：0/1/2 条撤下、
“同撤条数比移位裂缝数”的优选、连通性、贴签钉死、基准固定、
需要撤 3 条（超过上限）的无解、撞已复核对位的无解，以及 HTTP/表单/重置通道。

### 内置种子数据的两个标准情形

| 情形 | 点选（A 图 → B 图） | 结果 |
|---|---|---|
| **有解冲突**（页面按钮“填入有解冲突示例”） | `img1 (440,170)` → `img2 (40,170)`，同一朵莲纹 | 新对位 `DW-06` 已复核；必须撤 `DW-02、DW-03`（枚举确认不存在撤 0/1 条的解；撤 `DW-02+DW-05` 虽也可行但会多移 1 条裂缝，故不选）；`LF-03 (990,220)→(960,200)`、`LF-04 (1150,110)→(1120,90)` |
| **无解冲突**（页面按钮“填入无解冲突示例”） | `img0 (470,150)` → `img1 (20,150)` | 隐含位移 (450,0) 与已复核 `DW-01` 的 (400,0) 直接矛盾，已复核对位不可撤；枚举全部 7 种撤法（≤2 条）均不可行，原图与 5 条对位不变 |

## HTTP / JSON 接口

| 方法与路径 | 说明 |
|---|---|
| `GET /` | 操作页（总图、点选台、对位/裂缝台账、处理记录、结果横幅） |
| `POST /submit` | 无 JS 也可用的表单提交，PRG 跳转到 `/?run=<id>` |
| `POST /reset` | 表单重置回内置示例 |
| `GET /api/state` | 全部图像（含当前平移）、对位、裂缝（含当前总图坐标）、记录、示例载荷 |
| `POST /api/submit` | JSON 提交：`{image_a,image_b,ax,ay,bx,by}`，返回求解与落库结果 |
| `POST /api/reset` | JSON 重置 |
| `GET /api/runs/<id>` | 某次提交的完整结果 |
| `GET /healthz` | 健康检查 |

`POST /api/submit` 的 `status`：

- `applied`：含 `removed[]`（撤下对位快照）、`shifted[]`（裂缝 `old/new/delta` 坐标）、
  `new_alignment.code`；
- `no_solution`：含 `reason` 与尝试过的候选数，数据库无改动；
- `invalid`（HTTP 400）：选图相同、坐标越界等输入问题。

## 代码结构

```
app/
  seed_data.py     # 样片/旧对位/裂缝/示例点 的唯一数据来源 + 播种/重置
  solver.py        # 纯逻辑：约束传播、连通性、贴签钉、枚举 ≤2 撤法、双目标优选
  services.py      # 校验 + 求解 + SQLite 事务（应用或整体不动）
  db.py            # 连接、schema、初始化
  scene.py         # 由 seed_data 生成样片 SVG（python -m app.scene）
  __init__.py      # Flask 工厂与路由（页面 + JSON API）
  templates/       # base.html / index.html
  static/          # style.css、app.js（坐标换算与点选标记）、samples/*.svg
tests/             # test_solver.py、test_api.py
selftest.py        # 一键跑全部用例并说明两种关键情形
Dockerfile / docker-compose.yml / requirements.txt
```

## 本次完工核对说明

**已实现**：上述全部业务规则、页面、API、SQLite 持久化、Docker/Compose 文件、自测。

**已验证（在开发沙箱内实际执行）**：

- `python selftest.py` / `pytest -q`：21 个用例全部通过；
- 用 Flask 开发服务器和与 Docker 相同参数的 gunicorn
  （`--workers 2 --preload wsgi:application`）实际启动，
  经 HTTP 验证了有解落库、无解不变、表单 302、重置、静态 SVG、健康检查；
- `node --check static/app.js` 通过；5 个 SVG 均为合法 XML；
  `docker-compose.yml` 通过 YAML 解析。

**未在此环境验证 / 未完成**：

- 该沙箱内没有安装 Docker CLI/守护进程，因此 **`docker compose up --build`
  本身没有在本机实际跑过**；Dockerfile 仅基于 `python:3.12-slim` 安装
  `requirements.txt` 并以已验证的 gunicorn 命令启动，配置已做静态校验。
- 沙箱内没有无头浏览器，未做像素级/真实点击的浏览器自动化验证；
  点选坐标按 `getBoundingClientRect()` 与样片原始 480×360 比例换算，
  标记层与图片盒严格同尺寸。
