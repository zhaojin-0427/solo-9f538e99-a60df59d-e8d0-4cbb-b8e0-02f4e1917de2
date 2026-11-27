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

共 27 个 Python 用例（纯求解器 + Flask/SQLite 接口/事务/版本协议），覆盖：0/1/2 条撤下、
“同撤条数比移位裂缝数”的优选、连通性、贴签钉死、基准固定、
需要撤 3 条（超过上限）的无解、撞已复核对位的无解，以及 HTTP/表单/重置通道、
增量 delta、`base_version` 冲突（409）与版本单调递增。

另有可选的真实浏览器端到端脚本 `tests/browser/e2e.js`（Playwright/Chromium，
68 项断言），覆盖不整页重载、滚动位置与未动图层保留、两标签页交错提交/重置、
旧响应晚到、网络失败保留现状等本次改造点。

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
| `GET /api/state` | 全部图像（含当前平移）、对位、裂缝（含当前总图坐标）、记录、示例载荷、`version` |
| `GET /api/version` | 仅返回当前数据版本 `{version}` |
| `POST /api/submit` | JSON 提交：`{image_a,image_b,ax,ay,bx,by,base_version}`，按版本返回增量或 409 |
| `POST /api/reset` | JSON 重置，返回新 `version` 与完整 `state` |
| `GET /api/runs/<id>` | 某次提交的完整结果 |
| `GET /healthz` | 健康检查 |

### 版本与增量协议（本次“不整页重载”改造）

SQLite `meta.state_version` 是总图/台账的数据版本，初始为 `1`：
**有解提交 +1、重置单调 +1（绝不回退），无解提交不变**。提交事务用
`BEGIN IMMEDIATE` 把“读版本 → 求解 → 落库 → 版本 +1”串行化，多 worker /
多标签页并发时同一版本只有一个提交能成功，其余拿到 `409`。

- `base_version` 等于当前版本时，`POST /api/submit` 返回：
  - `applied`：除原有 `removed[] / shifted[] / new_alignment.code` 外，
    另有新的 `version` 与 `delta`。`delta.images[]` **只含平移真的变化的样片**，
    `cracks[]` 只含随移动样片移位的裂缝新总图坐标，
    `alignment_marks_upsert[] / alignment_marks_remove[]` 分别是需要刷新几何
    （新对位 + 端点落在移动样片上的保留对位）和需要从总图删除的标记，
    以及 `alignments_upsert[] / removed_alignment_ids / alignment_total`。
    前端只 patch 这些节点，**没动的样片 `<g data-image-id>` 图层节点原样保留**。
  - `no_solution`：`version` 不变、`delta: null`，前端只切换结果区。
- `base_version` 过期（另一标签页已提交或重置）时返回
  `409 {status:"stale_state", version, state}`，**不写任何 run/对位**。
  前端随即 `GET /api/state` 重取完整总图与台账整体补齐（保留点选台输入），
  再用新版本自动重提一次。
- 前端用单调请求序号 + 响应版本号双重守卫：**较旧的响应晚到时直接丢弃**，
  页面保持已经显示的新状态；网络/5xx 失败不做乐观改动，总图与台账原样保留。
- 不带 `base_version` 的调用（旧脚本/测试）不做版本检查，行为与以前一致。

`POST /api/submit` 的 `status`：

- `applied`：含 `removed[]`（撤下对位快照）、`shifted[]`（裂缝 `old/new/delta` 坐标）、
  `new_alignment.code`，以及上述 `version / delta`；
- `no_solution`：含 `reason` 与尝试过的候选数，数据库无改动；
- `stale_state`（HTTP 409）：浏览器版本过期，附当前完整 `state`；
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
tests/             # test_solver.py、test_api.py（27 用例）；browser/e2e.js 为可选 Playwright 核对
selftest.py        # 一键跑全部 Python 用例并说明两种关键情形
Dockerfile / docker-compose.yml / requirements.txt
```

## 本次完工核对说明（不整页重载 / 增量 / 多标签页一致性）

**本次新增/改造的功能**：

- 提交改为 `fetch` JSON，不再整页重载；窗口与 `.map-scroll` 总图视口位置原样保留，
  结果内联展开在提交按钮上方（可收起），总图、两张台账、处理记录与结果在同一同步段切换。
- 新增 `meta.state_version` 版本号与增量 `delta` 协议（见上节）：同版只传变动，
  没动的样片图层 DOM 节点完全保留；移动样片的 `<g transform>`、随片裂缝台账坐标、
  保留对位标记几何、新对位标记、撤下标记删除、台账“已撤下”徽标/行样式均就地更新。
- 跨标签页：提交带 `base_version`；遇到另一标签页提交/重置造成的 `409 stale_state`，
  自动重取 `/api/state` 完整总图与台账补齐，再以新版本重提一次，并显示补齐提示。
- 竞态：单调 `latestSeq` + 响应版本号双守卫，晚到的旧响应整体丢弃；
  网络错误 / 5xx / 400 时不做任何乐观 DOM 改动，当前总图与台账保留并给出错误提示。
- 传统无 JS 表单 PRG 通道保持可用；新增 6 个版本/增量/冲突 Python 用例。

**已验证（在本沙箱内实际执行）**：

- `python -m pytest tests -q` / `python selftest.py`：**27 个 Python 用例全部通过**；
  `node --check app/static/app.js` 通过。
- 用与 Dockerfile 完全相同的 gunicorn 参数
  （`--workers 2 --preload wsgi:application`，独立临时 SQLite 库）实际启动，
  经 HTTP 验证：同版增量只含 `img2`、`base_version=1` 的旧客户端在提交后稳定收到
  `409`、无解版本不变且 `delta=null`、重置使版本单调 +1；
  8 个并发同版本提交恰好 1 个 `200`、7 个 `409`，无 5xx / 锁错误。
- 在沙箱内下载解压 Debian 依赖库到用户目录，让 Playwright 的真实 Chromium 跑起来，
  `tests/browser/e2e.js` **68 项断言全部通过**，覆盖：
  有解增量/无重载/滚动位置与未动节点保留、无解只更新结果、
  两个标签页交错提交（409→重取→重提）、交错重置、
  用 `page.route` 卡住并倒序放行响应验证旧响应不覆盖新状态、
  `route.abort` 网络失败保留现状及恢复后再提交、保留对位标记几何更新。
  另用真实鼠标按比例点选两张样片并点击提交成功，且截图人工核对了
  总图移位、标记增删、台账撤下/新行、裂缝新坐标与内联结果面板。
- 5 个 SVG 均为合法 XML，`python -m app.scene` 重新生成的文件与仓库版本逐字节一致；
  `docker-compose.yml` 通过 YAML 解析。

**未在此环境验证 / 剩下的工作**：

- 该沙箱内没有 Docker CLI/守护进程，且容器 `CapEff=0`、用户命名空间被禁，
  rootless Docker 也无法启动，因此 **`docker compose up --build` 本身没能在本机实跑**。
  已做的等价核对：Compose YAML 合法、按 `requirements.txt` 装依赖、
  `python -m app.scene` 成功、并用 Dockerfile 的同一条 gunicorn CMD 实际提供服务验证。
  Dockerfile / compose 沿用既有配置（命名卷 `mural-data` → `/data`，
  `WEB_PORT` 默认 5000），在具备 Docker 的环境执行 `docker compose up --build` 即可。
- 沙箱 Chromium 缺少中文字体，截图里中文显示为方框（不影响 DOM/行为断言）；
  在正常带中文字体的系统或用户浏览器中显示正常。
- 尚未做跨浏览器（Firefox/WebKit）与真实多人远程并发的验证；
  当前冲突策略是“过期即重取完整状态并自动重提一次”，
  若产品上希望冲突后改为“提示并等待修复师再次手动确认”，只需调整 `app.js`
  中 `stale_state` 分支（后端 409 与完整 `state` 已就绪，两种交互都容易实现）。
