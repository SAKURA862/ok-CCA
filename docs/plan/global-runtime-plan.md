# 全局运行时框架 · 总体实施计划

> 状态：待评审（尚未开始编码）
> 适用范围：`base_frame`（框架能力）+ `dev`（交错战线落地）
> 工作方式：每次只执行一个阶段，执行完停下等审查；下一阶段的细分拆解在审查通过后一起做。

## 0. 目标与边界

把「在游戏里、画面干净、站在正确页面」这三件事从每个任务里抽出来，变成框架级能力：

| 层 | 能力 | 解决的问题 |
| --- | --- | --- |
| A 启动层 | 启动游戏 / 处理登录页 | 任何任务执行前游戏一定就绪 |
| B 弹窗层 | 网络错误、公告、签到等弹窗 | 任意时刻的打断不再污染业务代码 |
| C 导航层 | 页面图 + 最短路 + 跳转缓存 | 任务之间可以直接跳转，不必回主页 |

三条硬约束（贯穿所有阶段）：

1. **不改 ok-script 本体**（`.venv\Lib\site-packages\ok` 一行不动）。
2. **唯一挂载点**：`MyBaseTask` 包装 `run()`，弹窗钩在 `next_frame()`，导航在任务开始时选路。
3. **每阶段独立可回滚**，失败证据（截图 + 日志 + 判定分数）必须落盘。

## 1. 分支策略

现状：

```
master        f134d07  ← 模板上游
base_frame    f0d458a  ← 纯框架，无游戏内容
dev           aabb9f1  ← base_frame + 交错战线启动任务
```

计划：

| 步骤 | 动作 | 说明 |
| --- | --- | --- |
| 1 | `git checkout base_frame` → `git checkout -b feat/global-runtime` | 框架开发在功能分支，`base_frame` 始终可发布 |
| 2 | P1–P4 在 `feat/global-runtime` 上分阶段提交 | 每阶段 1–3 个原子提交 |
| 3 | 阶段验收后 `git checkout base_frame && git merge --ff-only feat/global-runtime` | `base_frame` 前进，历史保持线性 |
| 4 | `git checkout dev && git rebase base_frame` | 把 `aabb9f1` 挪到新框架上 |
| 5 | P5 在 `dev` 上实现交错战线适配器 | 游戏专属内容不进 `base_frame` |

预期冲突：`aabb9f1` 改了 `src/config.py`、`src/ui/home_tab.py`，这两个文件 P1/P2 也会动，rebase 时手工合并，改动量小（单提交）。

`base_frame` 只放 `GameAdapter` 接口 + 一个 `NullAdapter`（未配置游戏时直接放行）；交错战线的参数与识别逻辑放 `dev`。

## 2. 阶段总览

| 阶段 | 内容 | 规模 | 交付物 |
| --- | --- | --- | --- |
| P0 | 基线整理：分支、设计稿入库、跑通现状 | S | `docs/plan/`、`docs/design/` 两份 HTML |
| P1 | A 启动层 | M | `src/games/`、`src/tasks/bootstrap.py`、`MyBaseTask` 包装 |
| P2 | B 弹窗层 | M | `src/overlays/`、`configs/overlays.json`、`daily_state` |
| P3 | C 导航层 | L | `src/nav/`、`ok_templates` 锚点、`configs/nav_cache.json` |
| P4 | 详情页「运行一次」+ 批量联动 | S | `src/ui/task_settings_tab.py`、`src/ui/home_tab.py` |
| P5 | 交错战线落地（dev） | M | `src/games/crosscore.py`、删除旧启动任务 |
| P6 | 文档与收尾 | S | `docs/crosscore.md`、`docs/framework.md`、截图 |

规模说明：S ≈ 半天内、M ≈ 1 天、L ≈ 2–3 天（含标定与验证）。

## 3. 各阶段细节

### P0 · 基线整理

- 分支：建 `feat/global-runtime`。
- 入库：`docs/design/bootstrap-design.html`、`docs/design/overlay-nav-design.html`、本计划。
- 回归：确认当前 `base_frame` 能启动 GUI（`python -m ok gui --mcp --config src.config:config`），MCP 可用。
- 验收：分支拓扑正确；`git status` 干净；GUI 正常起。

### P1 · 全局启动层（A）

交付：

```
src/games/base.py        GameAdapter 协议 + NullAdapter + BootstrapResult
src/tasks/bootstrap.py   ensure_ready(task, adapter, cfg) 状态机
src/tasks/MyBaseTask.py  __init_subclass__ 包装 run()；ensure_game_ready()
src/config.py            game_profile / bootstrap.{enabled,boot_timeout,enter_timeout,force_restart}
```

行为矩阵（验收即按此逐条测）：

| 起始状态 | 期望 |
| --- | --- |
| 游戏未运行 | 启动 → 等登录页 → 点击 → 进入，`LAUNCHED` |
| 停在登录页 | 直接点击，`TAPPED`，**不重启进程** |
| 加载页 | 等待转登录页；超时报错 + 截图 |
| 大厅/战斗 | 立即放行，`ALREADY_READY` |
| 未配置 `game_profile` | 跳过，`SKIPPED` |
| 设备不可用 | 抛错，不静默 |

验收：4 状态 × 3 入口（GUI 单跑 / CLI / MCP）各至少 1 次；`force_restart` 打开/关闭各 1 次对比。

风险：`__init_subclass__` 包装若破坏 MCP 的 `inspect` 校验 → 用 `functools.wraps` + 保持同步函数；一旦 MCP 拒收，退回“显式调用”并记录。

### P2 · 弹窗层（B）

交付：

```
src/overlays/registry.py  规则加载、匹配、节流、防死循环
src/overlays/actions.py   点击/ESC/固定坐标
configs/overlays.json     规则表
src/tasks/MyBaseTask.py   next_frame() 内挂 OverlayGuard
src/state/daily.py        跨日 04:00 判定（daily_pending）
```

验收：

1. 离线单测：用录好的帧 fixture（无弹窗 / 网络错误 / 公告 / 签到）验证命中与不命中，误报率 0；
2. 在线：真实触发一次网络错误（断网重连）并观察自动重试；
3. 防死循环：构造“关不掉的弹窗”，确认 3 次后抛错并截图；
4. 性能：开启前后同一任务耗时差 < 5%。

风险：线上弹窗难以稳定复现 → 以离线 fixture 为主证据，线上抓到一次即回归一次。

### P3 · 导航层（C）

交付：

```
src/nav/pages.py       PageDef + 锚点模板绑定
src/nav/graph.py       BFS/Dijkstra + 边有效性
src/nav/navigator.py   detect_current / goto / 跳转记录
configs/nav_cache.json 运行时学习结果
ok_templates/          首批锚点图 + coco_annotations.json 标注
```

首批页面（5 个）：主页、商店、任务、邮件、战斗结算。

验收：

1. 从任意一个已定义页面导航到任意另一个，成功率 100%（各跑 3 次）；
2. 第二次运行命中缓存，全量匹配次数为 0（日志可证）；
3. 人为把某边打断（关掉按钮）：自动回退 BFS 并重规划成功；
4. 未知页面：判 `unknown` 并报错，不盲点。

风险：作者成本高 → 若标定超过预期，P3 内追加“录制工具”作为子任务（单独评审）。

### P4 · 详情页「运行一次」+ 批量联动

交付：`src/ui/task_settings_tab.py` 标题区右侧按钮；`src/ui/home_tab.py` 批量调度改为 `goto(next_task.entry_page)`。

验收：详情页点击按钮 → 走同一条 `start_controller.start()`；批量两个任务，日志显示 TaskA 结束 → 导航 → TaskB，无回主页动作。

### P5 · 交错战线落地（dev）

交付：`src/games/crosscore.py`（识别参数、点击点、包名）；删除 `src/tasks/CrossCoreDaily.py`、`src/tasks/CrossCoreLauncher.py`；`src/config.py` 配 `game_profile: 'crosscore'`。

验收：冷启动 / 热启动（停在标题页）/ 已在大厅 三种状态 × MCP、CLI、GUI 各一次。

### P6 · 文档与收尾

- `docs/framework.md`：三层能力、配置项、如何加新游戏、如何加弹窗规则、如何加页面；
- `docs/crosscore.md` 更新为“交错战线适配说明”；
- 截图入库（启动/弹窗/导航各 2 张）；
- 分支合并完成，`git log` 每阶段可追溯。

## 4. 测试与证据规范

| 项 | 要求 |
| --- | --- |
| 单元/离线 | `tests/` 下用 fixture 帧跑判定逻辑，docker 无关、可重复 |
| 在线 | 每次运行落 `screenshots/<时间>_<阶段>_<结果>.png` |
| 日志 | 每阶段关键决策打一行结构化日志：`stage=overlay rule=network_retry score=0.97 action=tap(1180,760)` |
| 性能 | 记录开启前后任务耗时，写入阶段报告 |
| 回滚 | 每阶段一个 commit，`git revert <sha>` 即可整体回退 |

## 5. 风险清单

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| 模板标定成本高 | P3 延期 | 先做 5 页闭环；录制工具单独立项 |
| 游戏改版导致模板失效 | 三层都受影响 | 失败时输出 miss 截图 + 分数；文档写明重标流程 |
| 弹窗误判造成连点 | 破坏游戏状态 | 阈值宁高勿低；max_attempts=3；命中即截图 |
| `__init_subclass__` 与 MCP 校验冲突 | P1 阻塞 | 首日先做最小验证；不行则退化为显式调用 |
| 沙箱权限 | 写文件失败 | 需要 `danger-full-access` 的操作提前说明 |
| rebase 冲突 | 分支混乱 | P0 就把 `feat/global-runtime` 建好；冲突集中在 2 个文件 |

## 6. 工作方式（与你的约定）

1. 每个阶段开始前：我把该阶段拆成可验收的条目（任务清单 + 验收命令 + 风险），你确认后再动手。
2. 每个阶段结束：我停下，提交代码，给出证据（命令输出、截图路径、耗时），等你审查。
3. 审查通过后：一起拆解下一阶段，再执行。
4. 期间发现的新问题只记入 `docs/plan/backlog.md`，不顺手改代码。
