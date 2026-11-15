# 运行时框架

项目在 ok-script 之上加了三层「任务执行前后通用能力」。任务作者只写业务步骤，不用重复处理启动、弹窗和页面跳转。

| 层 | 作用 | 实现 |
| --- | --- | --- |
| 启动层 | 保证游戏可执行：未启动则启动，停在登录页则点登录 | `src/tasks/bootstrap.py`、`src/games/` |
| 弹窗层 | 拦截随时弹出的窗口与每日公告，保证画面干净 | `src/runtime/overlay.py`、`src/runtime/daily.py` |
| 导航层 | 识别当前页面，按图走到目标页面 | `src/nav/` |

三层都挂在 `src/tasks/MyBaseTask.py` 上：`__init_subclass__` 包装子类 `run()`，先 `ensure_game_ready()` 再执行原 `run()`；`next_frame()` 被覆写为「取帧 → 处理随时弹窗 → 卡住兜底」。

## 启动层

配置两处：`src/config.py` 的 `game_profile` 指定游戏，`game_bootstrap` 控制超时。

```python
'game_profile': 'crosscore',
'game_bootstrap': {'boot_timeout': 180, 'enter_timeout': 90,
                   'poll_interval': 0.6, 'force_restart': False},
```

新游戏需要实现 `src/games/base.py` 的 `GameAdapter`，再在 `src/games/registry.py` 注册：

```python
class GameAdapter(Protocol):
    name: str
    package_name: str
    def launch(self, task): ...          # 拉起游戏
    def is_login_screen(self, task): ... # 是否停在登录页
    def is_ready(self, task): ...        # 是否已进入可执行画面
    def tap_login(self, task): ...       # 点登录
```

`is_ready` 必须是「可以开始点业务按钮」的状态，不能用「App 在前台」代替：加载页也满足前台，会放行到业务逻辑。

单任务可设 `SKIP_GAME_BOOTSTRAP = True` 或 `game_profile = ''` 跳过启动层。

## 弹窗层

规则文件由 `configs/config.py` 的 `overlays.rules_file` 指定，示例见 `assets/overlays.example.json`：

```json
{"rules": [
  {"id": "network_retry", "when": ["anytime"], "template": "ov_network_retry",
   "roi": [0.3, 0.35, 0.7, 0.65], "threshold": 0.8, "action": {"type": "click_box"},
   "cooldown": 2.0, "max_attempts": 3},
  {"id": "daily_signin", "when": ["on_home"], "template": "ov_signin_icon",
   "daily": true, "action": {"type": "click_box"}}
]}
```

| 触发时机 | 谁调用 | 说明 |
| --- | --- | --- |
| `anytime` | `next_frame()` | 每次取帧都会检查，节流 0.3s |
| `after_login` | 启动层登录成功后 | 每日公告类弹窗的第一个落点 |
| `on_home` | 导航层回到主页后 | 需要配合导航层 |
| `on_stuck` | 业务 8s 没有调用 `report_progress()` | 兜底，避免业务被弹窗卡死 |

同一规则连续 `max_attempts` 次命中仍未消失会抛 `OverlayStuck` 并截图 `overlay_stuck_<id>`，而不是无限点。带 `daily: true` 的规则按本地 04:00 换日，一天只处理一次。

## 导航层

### 图配置

`assets/nav/<profile>.json`，profile 取任务的 `nav_profile`，未设置时取 `game_profile`：

```json
{
  "pages": [
    {"id": "home", "name": "主页", "anchors": ["nav_home_tab"], "is_home": true},
    {"id": "arena", "name": "镜像竞技", "anchors": ["nav_arena_title"]}
  ],
  "edges": [
    {"from": "home", "to": "arena",
     "action": {"type": "click_template", "template": "nav_home_to_arena"}}
  ]
}
```

页面节点：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `id` / `name` | 是 | `id` 用于代码引用 |
| `anchors` | 是 | 页面视觉指纹，当前恒为 1 个模板名 |
| `is_home` | 否 | 家页，全量扫描时最后试 |
| `tags` | 否 | 预留分组标签 |

边：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `from` / `to` | 是 | 有向；回程要另写一条 |
| `action` | 是 | `click_template` / `click_point` / `key` |
| `timeout` | 否 | 默认 8s |
| `retries` | 否 | 默认 1 |
| `cost` | 否 | 寻路权重，默认 1.0 |

页面用「一个锚点」判定即可：同一大页面的不同页签各建一个节点，锚点裁在选中态页签上。面板、弹窗、战斗、结算不是页面，不要建节点。

### 模板规范

模板放在 `assets/templates/`，扁平存放，用前缀分区：`nav_`（页面锚点与跳转按钮）、`ov_`（弹窗）、`<task>_`（业务）。

文件名必须是 `<name>_<屏宽>x<屏高>_<x>_<y>.png`，宽高是**源截图分辨率**（本项目统一 1920x1080），x/y 是裁切左上角。命名不合规会抛 `TemplateFormatError`，表现为所有页面都识别不到。

框架按 `min(帧宽/基准宽, 帧高/基准高)` 等比缩放模板，因此 16:9 的 1280x720 / 1920x1080 / 2560x1440 共用一套模板；非 16:9 只影响贴边的锚点。

### 任务里怎么用

```python
class ArenaTask(MyBaseTask):
    entry_page = 'arena'      # 批量调度会把任务送到这里
    home_page = 'home'        # 收尾回主页，可选

    def run(self):
        with self.on_page('arena'):
            self.click('arena_challenge')
        self.goto('home')
```

| 接口 | 作用 |
| --- | --- |
| `current_page()` | 识别当前页，识别不到抛 `NavUnknownPage` |
| `goto(page)` | 按图走过去，返回走过的路径 |
| `ensure_page(page)` | 幂等版 `goto`，已在目标页不动 |
| `on_page(page)` | 上下文管理器，进入后执行一段逻辑 |
| `nav_back()` | 按导航历史回退（不是设备返回键） |

定位只做两层：先试 `last_page` 的锚点，不中再全量扫描，仍不中直接报错，绝不盲点。寻路用 Dijkstra，失败边按 `cost × (1 + 0.5 × fails)` 降权；同一跳连续失败 2 次本轮禁用。成功跳转写入 `configs/nav_cache.json`，下次优先走熟路。

失败时截图 `nav_step_failed_<from>_<to>`；定位失败截图 `nav_unknown`。

### 配置

```python
'nav': {'graph_file': '', 'cache_file': '', 'threshold': 0.8,
        'settle_time': 0.3, 'max_hops': 6},
```

`graph_file` / `cache_file` 留空时分别落到 `assets/nav/<profile>.json` 与 `<config_folder>/nav_cache.json`。`settle_time` 用于等待目标锚点稳定，避免点击动画造成的假命中。

## 编排层

两种驱动器共用一个 `Step` 原语：简单任务用 `Flow` 顺序执行，复杂任务用 `StateMachine` 按守卫转移。任务只需要实现 `build_flow()`，默认 `run()` 会执行它。

### Step 字段

| 字段 | 说明 |
| --- | --- |
| `name` | 步骤名，用于日志与失败截图 |
| `goto` | 执行前先 `ensure_page` 到该页；只写 `goto` 就是纯导航步骤 |
| `action` | 输入动作对象，如 `Click('x')`，见「动作层」 |
| `click` | 语法糖，等价于 `Click(target)`，目标可为模板/坐标/框/lambda |
| `double_click` / `right_click` / `long_press` | 语法糖，分别等价 `DoubleClick` / `RightClick` / `LongPress` |
| `key_press` | 语法糖，等价于 `KeyPress(...)` |
| `call` | 自定义函数（可传任务方法），返回值写入 `task.data[name]` |
| `wait` | 动作后必须出现的模板名（默认等 8s，`settle_time=0.3`） |
| `expect` | 额外断言 `lambda task: bool` |
| `retry` | 失败重试次数，默认 1 |
| `on_fail` | `retry` / `skip` / `abort`，默认 `abort` |
| `optional` | 为真时失败只记警告并继续 |
| `when` | 前置守卫 `lambda task: bool`，为假时跳过整步（不算失败） |
| `action` 简写 | `click=` / `double_click=` / `right_click=` / `long_press=` / `key_press=` |

`action` 与 `call` 互斥；语法糖与 `action` 互斥且一次只能用一个；三者都没给时必须给 `goto`。失败重试用尽后截图 `flow_fail_<任务>_<步骤>`。同容器内步骤名必须唯一。

### 流程收尾与提前结束

```python
Flow(steps, final=[Step('回主页', goto='home')])      # final 无论成功失败都执行
Step('x', click='y', when=lambda t: t.data['enabled'])  # 条件跳过
Flow([... , Stop('次数用完')])                          # 主动结束，final 仍执行
Step('check', call=lambda t: t.stop_if(cond, '够了'))    # 在 call 里结束
```

### 动作层

`action` 只负责「产生一次外部输入」，不读数据、不决定流程；读数据用 `call`，导航用 `goto`，等待与断言用 `wait` / `expect`。

所有动作都支持三种目标，**只能给一个**：

| 写法 | 含义 |
| --- | --- |
| `'arena_deploy_button'` | 模板匹配，按 `relative` 取框内点（默认中心） |
| `(0.87, 0.90)` | 归一化坐标；两分量都 ≤1 时按归一化处理，否则当像素 |
| `(120, 200, 300, 260)` | 业务函数算出的像素框 |

| 动作 | 关键参数 | 底层 |
| --- | --- | --- |
| `Click` | — | `click` |
| `DoubleClick` | `interval=0.12` | 两次 `click` |
| `LongPress` | `hold=1.0` | `input motionevent DOWN/UP` |
| `RightClick` | — | `click(key='right')` |
| `Swipe` | `start` / `end` / `duration=0.5` | `swipe`，保留惯性 |
| `Drag` | `start` / `end` / `duration=0.6` / `hold=0.2` | 分段 `motionevent`，抬起前停住 |
| `KeyPress` | `key` / `hold=0.02`，`hold>0.15` 走长按 | `send_key` / `send_key_down`+`send_key_up` |
| `KeyCombo` | `keys` / `hold=0.05` | 依次按下、逆序抬起 |
| `InputText` | `text` + 可选目标 / `settle=0.4` | 先点击目标再 `input_text` |

```python
Flow([
    Step('长按卡片', action=LongPress('arena_card', hold=1.2)),
    Step('下滑列表', action=Swipe(start='arena_list_top', end=(0.5, 0.25), duration=0.6)),
    Step('精确拖到起点', action=Drag(start=(0.5, 0.8), end=(0.5, 0.3), hold=0.2)),
    Step('搜索', action=InputText('sword', 'search_box')),
    Step('关掉面板', action=KeyPress('escape')),
])
```

`Swipe` / `Drag` 的 `start`、`end` 是「目标简写」：字符串当模板名、二元组当坐标、四元组当框、函数运行时求值。`InputText` 不给目标时直接输入（适合已经点过输入框的场景），只支持 ASCII，空格自动转 `%s`。

### 线性：Flow

```python
class DailySignInTask(MyBaseTask):
    entry_page = 'home'

    def build_flow(self):
        return Flow([
            Step('打开签到', click='nav_home_signin', wait='signin_title'),
            Step('领取', click='signin_claim', wait='signin_claimed', optional=True),
            Step('关闭', click='signin_close', wait='home_marker'),
        ])
```

### 状态机：StateMachine

```python
class ArenaTask(MyBaseTask):
    entry_page = 'arena'

    def build_flow(self):
        return StateMachine({
            'refresh': State('refresh', do=self.read_left,
                             transitions=[(lambda t: t.data['left'] <= 0, 'done'),
                                          (lambda t: True, 'pick')]),
            'pick': State('pick', do=self.choose_opponent,
                          transitions=[(lambda t: True, 'fight')]),
            'fight': State('fight', do=[Step('挑战', click='arena_challenge')],
                           transitions=[(lambda t: True, 'refresh')]),
            'done': State('done', do=self.log_summary),
        }, max_transitions=50)
```

`State.do` 可以是函数、单个 `Step` 或 `Step` 列表；`goto` 在进入状态前执行；`transitions` 按顺序取第一个为真的守卫，都不命中即结束。转移次数超过 `max_transitions` 抛 `FlowFailed`；同一状态原地打转会记一条 `flow: 没有进展` 警告。

### 与其它层的关系

- 每步执行前自动 `ensure_page`，导航层负责「在哪」，编排层负责「做什么」；
- 每步结束调用 `report_progress()`，弹窗层的 8s 卡住判定不会误报；
- 每步记一条 `flow: <步骤> (120ms)` 日志，日志页可见。

## 任务调用任务（设计，P3.6 实现）

ok-script 只调用无参的 `task.run()`，也不接收返回值。要让一个任务带上参数和返回值，由框架提供基类适配，而不是让开发者额外写胶水函数。

### `CallableTask`

```python
class BattleTask(CallableTask):
    SKIP_GAME_BOOTSTRAP = True

    def execute(self, origin: str, timeout: float = 180.0) -> BattleResult:
        ...
        return BattleResult(outcome, rewards, elapsed)
```

开发者只写 `execute(...)`：签名就是参数表，`return` 就是返回值。基类的 `run()` 负责：

1. 调 `ensure_game_ready()`（启动层照常生效）；
2. 用 `inspect.signature` 绑定 `self.call_args`，缺必填参数时抛 `TaskCallError('BattleTask 需要参数：origin')`；
3. 调 `execute(**kwargs)`，结果存进 `self.result` 并返回。

GUI / CLI / MCP 仍然调无参 `run()`，未传的必填参数会得到上面那句明确报错，而不是参数栈。

### 调用方

```python
Step('挑战', click='arena_challenge',
     call=lambda t: t.call_task(BattleTask, origin='arena', timeout=240))
Step('赢了继续', expect=lambda t: t.data['挑战'].win)
```

`call_task` 的语义：同步阻塞、返回 `execute` 的返回值、`Step(call=...)` 自动写入 `task.data[步骤名]`。

- 重入保护：同一任务在调用链上出现两次直接抛错，嵌套深度上限 3；
- 内层跳过启动层（外层已经拉起游戏）；
- 内层导航共享外层的 `last_page` 提示，不重复全量扫描；
- 内层异常包成 `TaskCallError('<外层> -> <内层>: ...')` 并留 `call_fail_<任务>` 截图；
- 每次调用清空内层 `data`/`result`，避免上次残留。

### helper 任务不进 GUI

`src/config.py` 的 `helper_tasks` 声明的任务只实例化，不加入 `onetime_tasks`/`trigger_tasks`，因此首页、任务设定、MCP `list_tasks` 都看不到它们。它们仍是普通 `MyBaseTask` 子类，导航、弹窗、编排、启动层全部继承。

### 装饰器（可选糖）

```python
@callable_task(name='战斗', icon=FluentIcon.GAME)
def battle(task, origin: str, timeout: float = 180.0) -> BattleResult:
    ...
```

等价于生成一个 `CallableTask` 子类，注册仍走 `helper_tasks` 或 `helpers.register()`。

### 战斗 / 扫荡 / 战利品都写成任务

框架不再提供 `BattleAdapter` 之类的协议。三者都是 helper 任务，通过 `call_task` 组合：

| 任务 | 输入 | 输出 |
| --- | --- | --- |
| `BattleTask` | `origin`、`timeout` | `BattleResult(outcome, rewards, duration)` |
| `SweepTask` | `stage`、`times`、`use_battle` | `Loot` |
| `LootTask` | 展示形态、区域 | `Loot` |

- 扫荡不是战斗的一种：能扫荡就用扫荡面板，不能或次数不足时再按 `use_battle` 循环调用 `BattleTask`；
- 战利品有三种展示形态，由 `LootTask` 内部按形态读取，统一返回 `LootItem(name, count, rarity)` 列表：

| 形态 | 读取方式 | 关闭方式 |
| --- | --- | --- |
| 竞技场弹窗（代币） | 弹窗正文 ROI 做 OCR，正则取 `名称 x 数量` | 点关闭按钮 |
| 胜利页右下奖励 | 右下区域横向翻页，逐格 OCR 名称与数量 | 点空白 / 关闭按钮 |
| 扫荡结算（左上成功、右侧逐次、右下总计） | 右下总计为权威，右侧逐次作明细；两者不一致记警告 | 点关闭按钮 |

- 上锁这类副作用放进 `LootPolicy`：默认 `dry_run`、先判已锁、单次上限、失败只记警告。

## 已知限制

- 导航只支持模板匹配，不做 OCR 页面识别。
- 图需要手工标注：每页 1 张锚点、每条边 1 张按钮模板。
- `Drag` / `LongPress` 依赖 `input motionevent`（Android 11+），不支持时自动退回 `swipe` / `mouse_down`。
- `RightClick` 只对支持右键的交互方式（PostMessage、pynput 等）有效，ADB 会当普通点击。
- `InputText` 只支持 ASCII；中文需要剪贴板或输入法方案。
- 弹窗规则只订阅 `logging.getLogger("ok")`；项目外的日志不会进入日志页。
- 底边栏日志的「暂停」只作用于页面视图，面板继续刷新。
