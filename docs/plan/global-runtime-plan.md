# 全局运行时框架 · 总体实施计划

> 状态：P0–P2 已完成（`6a0dd12` / `2c2f1bc` / `74e2cf2` / `efb5159`）；P3 设计已定稿，待动手
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
| P0 | 基线整理：分支、设计稿入库、跑通现状 ✅ | S | `docs/plan/`、`docs/design/` 两份 HTML |
| P1 | A 启动层 ✅ | M | `src/games/`、`src/tasks/bootstrap.py`、`MyBaseTask` 包装 |
| P2 | B 弹窗层 ✅ | M | `src/runtime/overlay.py`、`src/runtime/daily.py`、`assets/overlays.example.json` |
| P3 | C 导航层（页面图 + 寻路） | L | `src/nav/`、`assets/nav/<profile>.json`、`configs/nav_cache.json` |
| P3.5 | 编排层（Flow / Step）✅ | M | `src/flow/steps.py`、`MyBaseTask.build_flow()` |
| P3.6 | 任务调用任务（helper task） | S | `src/runtime/callable.py`、`src/runtime/helpers.py`、`MyBaseTask.call_task()` |
| P3.7 | 战斗 / 扫荡 / 战利品（任务形式） | M | `BattleTask`、`SweepTask`、`LootTask` |
| P3.8 | 战利品策略（上锁） | S | `LootPolicy`、`LockGoodChips` |
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
src/runtime/overlay.py     规则加载、匹配、节流、防死循环（OverlayGuard / OverlayRule）
src/runtime/daily.py       跨日 04:00 判定（game_day / DailyState）
assets/overlays.example.json  4 条示例规则（默认全部 disabled）
src/tasks/MyBaseTask.py    next_frame() 内挂 run_overlays；run_overlays('after_login'/'on_home') 入口
src/tasks/bootstrap.py     _wait_ready 成功后触发 after_login
src/config.py              overlays.{rules_file,min_interval}
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
src/nav/model.py       PageDef / EdgeDef / NavGraph + load_graph() 加载期校验
src/nav/locator.py     locate(graph, task)：last_page 优先 → 全量锚点扫描 → unknown 报错
src/nav/router.py      find_path(graph, start, goal, heuristic=None, max_hops=6)：Dijkstra（h=0）
src/nav/navigator.py   goto / ensure_page / on_page / 跳转记录与缓存
src/nav/actions.py     action 执行器（click_template / click_point / key），新增动作只改这里
assets/nav/<profile>.json  页面图（home + pages + edges）
configs/nav_cache.json     运行时学习结果（transitions）
ok_templates/              锚点图 + coco_annotations.json 标注
```

#### 数据模型（节点 / 边）

配置只有一个 JSON（`assets/nav/<profile>.json`），两段：`pages` 与 `edges`。瞬时画面（战力面板、战斗、结算）不进图——那是步骤层的 `wait` 断言与 P3.6 战斗运行时的事。

节点 = 一个「能被认出来的页面」，只描述「是什么」，不存坐标（必填 3 项，可选 2 项）：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `id` | str | 是 | 唯一键；任务用 `entry_page` 引用，边的 `to` 也用它 |
| `name` | str | 是 | 仅用于日志与报错文案 |
| `anchors` | list[dict] | 是 | 页面视觉指纹：`[{"template": str, "roi": [x1,y1,x2,y2]?, "threshold": float?}]`，指向 `ok_templates/` 的模板名。**当前恒为长度 1**；数组保留只为将来支持「多锚点与运算」，届时语义为全部命中 |
| `is_home` | bool | 否 | 主页/大厅标记；全文件恰好一个（加载期校验），批量调度的默认起点 |
| `tags` | list[str] | 否 | 调度软标签（`daily`/`weekly`），不参与寻路 |

不设 `notes`（注释写在文档里，不写进数据）、不设 `optional_anchor` 这类弱判据。

页签即页面：同一大页面下的不同页签各建一个节点，锚点裁在**选中态**的页签上（未选中灰、选中白/黄），一个模板即可判定。

边 = 「在 from 页面上做一个动作，到达 to 页面」，只描述「怎么走」（必填 3 项，可选 3 项）：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `from` / `to` | str | 是 | 节点 id，**有向** |
| `action` | dict | 是 | `{"type": "click_template"\|"click_point"\|"key", "template": str, "roi": [x1,y1,x2,y2]?, "point": [x,y]?, "key": str?}`；`roi` 限定搜索区可压低误匹配（ROI 内匹配 5–15ms，全屏 30–60ms） |
| `timeout` | float | 否 | 单跳超时，默认 **8.0s**（内部走 `wait_feature`，`settle_time=0.3`）；不依赖全局 `wait_until_timeout` |
| `retries` | int | 否 | 失败重试次数，默认 **1**；重试前重新定位当前页，不做无限循环 |
| `cost` | float | 否 | 寻路权重，默认 **1.0**；慢或易失败的跳转调大（如 2.0）即可被绕开 |

不设 `verify`：一跳的验证就是 `to` 的锚点——边的意义就是「点完能到 to」。也不设 `bidirectional`：反向动作需要自己的模板（返回键），自动生成的反边没有可点的东西；回程请显式写一条边。通用返回键属于运行时历史栈（`self.back()`，记 `last_page` 栈），不是图的边，留到 P3 之后再评估。

模板文件名必须是 `<name>_<屏宽>x<屏高>_<x>_<y>.png`（宽高是**源截图分辨率**，x/y 是裁切左上角，`FeatureSet._parse_crop_filename` 会校验 `x < 屏宽`）。命名不合规会抛 `TemplateFormatError`，导致该模板源整体不可用，表现为「所有页面都识别不到」。


#### 运行时

定位（`locator.locate`）只做两层，不做「猜」：

1. 先试 `last_page` 的锚点（1 次 ROI 匹配，5–15ms）；
2. 不中则**全量扫描**所有 page 的锚点（15 页 × 1 锚点 ≈ 0.2–0.3s）；
3. 全不中 → 抛 `NavUnknownPage`：截图 `nav_unknown`、打日志、终止本次导航。绝不盲点。

寻路（`router.find_path`）：二叉堆实现的 Dijkstra，`f = g + h`，`heuristic=None` 时 `h≡0`（等价 BFS）；接口保留 `heuristic` 参数，将来有可采纳启发函数时接上即变 A*，调用方不改。约束：

- `max_hops` 默认 **6**，超限判「无合理路径」并抛错（列出候选边），避免绕出七八跳；
- `start == goal` 直接早退；
- **缓存优先**：同代价时优先 `nav_cache.json` 里 `hits` 高的边；
- **失败边降权**：有效代价 `cost × (1 + 0.5 × fails)`；连续 2 次失败本轮禁用该边。

执行一跳（`navigator._walk`）：执行 `action` → `wait_feature(to.anchors[0].template, timeout, settle_time=0.3)` → 成功写 `last_page` 与 `hits`；失败按 `retries` 重试（重试前重新定位），仍失败截图 `nav_step_failed_<from>_<to>`、`fails += 1` 并抛错。

运行时状态（`configs/nav_cache.json`）：`last_page`、`transitions{"from>to": {"edge", "hits", "fails", "last"}}`。缓存只记「哪条边好走」，不代替锚点校验。

任务侧接口：

```python
class ArenaTask(MyBaseTask):
    entry_page = "arena"      # 批量运行时框架据此 goto；不写则不导航（老任务零改动）
    home_page = "home"        # 可选：跑完回主页

    def run(self):
        self.ensure_page("arena")     # 幂等：已在就不动
        self.goto("shop")             # 强制寻路到某页
        with self.on_page("arena"):   # 进块前确保
            ...
```

到达主页时顺带 `run_overlays('on_home')`，触发 `on_home` 类弹窗规则。

加载期校验：`id` 唯一、`from/to` 存在、`home` 存在且 `is_home` 恰好一个、锚点 `template` 在 feature set 中存在、无出边的页面给 warning（不致命）。

首批页面（P3 只落 2 页跑通机制，P5 再补齐）：`home`、`arena`。真实的商店/任务/编队/邮件锚点留到 P5 采。

验收：

1. 已定义页面两两互达，成功率 100%（各跑 3 次）；两页至少 3 条边（含一条两步路径）；
2. 第二次运行命中缓存：全量扫描次数为 0（日志可证）；
3. 人为关掉某条边的按钮：`fails` 累加 → 连续 2 次后该边被禁用并重规划成功；
4. 未知页面：抛 `NavUnknownPage` + 截图，不产生任何点击；
5. `max_hops` 生效：构造一条需要 7 跳的请求，确认抛错而不是硬走；
6. 离线单测：合成图（无设备）覆盖定位/寻路/缓存/失败路径。

风险：作者成本高（每页 1 张锚点、每条边 1 张按钮模板）→ 若标定超预期，P3 内追加「录制工具」作为子任务（单独评审）。

### P3.5 · 编排层（Flow / Step）

目标：任务逻辑不写流水账，用「带守卫的步骤流」，由框架负责“到位—动作—确认—失败恢复”。

交付：

```
src/flow/steps.py        Step / Flow / StateMachine
src/tasks/MyBaseTask.py  build_flow() + 默认 run() 驱动（子类只写 flow）
tests/test_flow.py       合成 flow 单测（无设备）
```

`Step` 字段：

| 字段 | 说明 |
| --- | --- |
| `name` | 步骤名，日志与截图里用 |
| `goto` | 进入本步前要到达的页面（page id） |
| `click` / `click_point` / `key` / `call` | 动作四选一；`click_point` 支持 `lambda task:` 动态坐标 |
| `wait` | 动作后要出现的瞬时画面模板名（弹窗/面板），只写模板，不新增实体 |
| `retry` / `on_fail` | 重试次数与失败策略（`raise` / `skip` / 指定恢复步骤） |
| `optional` | 失败不致命，记 warning 继续 |
| `branch` | 按 `task.state(key)` 选择下一步（返回 `Step` 或 `None` 结束） |
| `battle` / `result_key` | 触发 P3.6 战斗运行时并把 `BattleResult` 存进 state |

执行语义：`ensure(goto)` → 动作 → `wait(wait, settle_time=0.3)` → 成功进下一步；失败 `retry` → 恢复（重新 `ensure`）→ 仍失败按 `on_fail` 处理并截图 `flow_step_failed_<name>`。

复杂任务（循环、多分支）用 `StateMachine(states={...}, max_transitions=50)`，每个 `State` 写 `goto|click|tick` 与 `transitions=[(guard, target)]`；超出 `max_transitions` 抛错，防死循环。

验收：合成 flow 覆盖 顺序/分支/重试/optional/循环上限 五类；真实任务在 P5 落地时跑通（镜像竞技）。

### P3.6 · 任务调用任务（helper task）

目标：不引入战斗专用模块。框架只提供「任务之间同步调用」的能力，战斗、扫荡、战利品都由普通任务实现并组合。

背景：ok 只调用无参 `task.run()` 且忽略返回值；`BaseTask.run_task_by_class()` 已具备「同步 + 共享 info + 异常回传」，但要求被调任务注册在 `onetime_tasks`/`trigger_tasks`，会出现在 GUI 里。

交付：

```
src/runtime/callable.py   CallableTask 基类、callable_task 装饰器、TaskCallError
src/runtime/helpers.py    helper 注册表（不进 GUI 枚举）
src/tasks/MyBaseTask.py   call_task()、call_args/result、重入保护、check_stop()
tests/test_call_task.py   7 例离线测试
```

契约：

- `helper_tasks`（`src/config.py`）里声明的任务只实例化、不加入 `onetime_tasks`/`trigger_tasks`，因此 GUI、MCP `list_tasks` 完全看不到；
- 开发者继承 `CallableTask`，只写 `execute(...)`（带参、有返回值），`run()` 由基类适配：绑定参数、缺参报错、调 `execute`、把返回值存入 `self.result`；
- 调用方用 `self.call_task(BattleTask, origin='arena')`，返回 `execute` 的返回值；`Step(call=...)` 会自动写进 `task.data[步骤名]`；
- `call_task` 负责重入保护（深度上限 3）、跳过内层启动层、共享导航 `last_page`、异常包裹成 `TaskCallError('<外层> -> <内层>: ...')` 并截图；
- GUI 单独点开 helper：必填参数缺失时由基类抛出「需要参数：origin」的明确错误。

验收：7 例离线测试全绿；在真机上用一个 helper 任务被主页任务调用一次（P5 阶段随交错战线验证）。

### P3.7 · 战斗 / 扫荡 / 战利品（以任务形式实现）

不做 `BattleAdapter` 协议、不做 `src/runtime/battle.py`。三者都是任务：

| 任务 | 输入 | 输出 | 说明 |
| --- | --- | --- | --- |
| `BattleTask` | `origin`、`timeout` | `BattleResult(outcome, rewards, duration)` | 等进战 → 开自动/最高速 → 轮询胜负 → 关结算 → 回位校验 |
| `SweepTask` | `stage`、`times`、`use_battle` | `Loot` | 首选扫荡；无扫荡或次数不足时按 `use_battle` 循环调用 `BattleTask` |
| `LootTask` | 形态、区域 | `Loot` | 三种展示形态：弹窗、胜利页右下横向、扫荡三区域 |

战利品抽象（仍是任务内部实现，不上升为框架协议）：

- `LootItem(name, count, rarity)` / `Loot(items, source, raw_text)`；
- 通用读取助手：`scroll_collect(region, direction, max_pages)`、`read_items(region, rows, cols)`；
- 扫荡结算以右下「全部奖励」为权威，右侧逐次为明细，不一致时记警告。

### P3.8 · 战利品策略（上锁等）

`LootPolicy` 作为任务内的可插拔策略，不阻塞主流程：

- `dry_run=True` 默认只报告「将会上锁 N 个」；
- 先判「已上锁」再点，保证幂等；
- 单次上限 `max_locks`，任何一步失败只记警告并跳过；
- 品质阈值放任务 `default_config`（下拉：3 星以上 / 4 星以上 / 只锁 5 星），玩家可调。

验收：资源关刷取后先 dry-run 报告，再真实上锁 1 个并复核。

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
| 模板标定成本高 | P3 延期 | P3 先落 2 页闭环（home/arena），其余页随 P5 采；录制工具单独立项 |
| 游戏改版导致模板失效 | 三层都受影响 | 失败时输出 miss 截图 + 分数；文档写明重标流程 |
| 弹窗误判造成连点 | 破坏游戏状态 | 阈值宁高勿低；max_attempts=3；命中即截图 |
| `__init_subclass__` 与 MCP 校验冲突 | P1 阻塞 | 首日先做最小验证；不行则退化为显式调用 |
| 沙箱权限 | 写文件失败 | 需要 `danger-full-access` 的操作提前说明 |
| rebase 冲突 | 分支混乱 | P0 就把 `feat/global-runtime` 建好；冲突集中在 2 个文件 |
| helper 任务共享 executor 状态 | 嵌套调用互相污染 | `call_task` 统一重置 `data`/`result`、跳过内层启动层、共享导航只读 `last_page`；重入直接抛错 |
| 战利品三种形态差异大 | 读取逻辑碎片化 | 统一 `LootItem`/`Loot` + 两个滚动/网格助手；扫荡以总计为权威 |

## 6. 工作方式（与你的约定）

1. 每个阶段开始前：我把该阶段拆成可验收的条目（任务清单 + 验收命令 + 风险），你确认后再动手。
2. 每个阶段结束：我停下，提交代码，给出证据（命令输出、截图路径、耗时），等你审查。
3. 审查通过后：一起拆解下一阶段，再执行。
4. 期间发现的新问题只记入 `docs/plan/backlog.md`，不顺手改代码。
