# 编排与任务调用 · 快速开始

用结构化的步骤描述任务：点哪里、等什么、失败了怎么办、什么时候换流程。

标注：✅ 已实现。

## 0. 最小可用任务

```python
from src.flow import Flow, Step
from src.tasks.MyBaseTask import MyBaseTask


class SigninTask(MyBaseTask):
    name = 'Daily Signin'
    entry_page = 'home'

    def build_flow(self):
        return Flow([
            Step('open_panel', click='nav_signin', wait='signin_title'),
            Step('claim', click='signin_claim', wait='signin_claimed', optional=True),
            Step('close_panel', click='signin_close', wait='nav_home_anchor'),
        ])
```

`build_flow()` 返回流程，`run()` 由基类提供（启动层 → 流程）。

## 1. Step 字段

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `name` | `str` | 必填 | 步骤名，用于日志与失败截图；同一容器内唯一 |
| `goto` | `str` | `None` | 执行前导航到该页；只写它即为纯导航步骤 |
| `action` | `Action` | `None` | 完整动作对象 |
| `click` | 目标 | `None` | 糖：`Click(target)` |
| `double_click` | 目标 | `None` | 糖：`DoubleClick(target)` |
| `right_click` | 目标 | `None` | 糖：`RightClick(target)` |
| `long_press` | 目标 | `None` | 糖：`LongPress(target)`，`hold=1.0` |
| `key_press` | `str` | `None` | 糖：`KeyPress(key)` |
| `call` | `f(task) -> Any` | `None` | 读数据/算坐标，返回值存 `data[name]` |
| `wait` | `str` | `None` | 动作后必须出现的模板，默认 8s |
| `expect` | `f(task) -> bool` | `None` | 断言，False 即本步失败 |
| `retry` | `int` | `1` | 整步重试次数 |
| `on_fail` | `retry`/`skip`/`abort` | `abort` | 重试用尽后的行为 |
| `optional` | `bool` | `False` | 失败只记警告，等价 `on_fail='skip'` |
| `when` ✅ | `f(task) -> bool` | `None` | 为假时跳过整步 |

约束：五个糖最多一个且与 `action` 互斥；`action` 与 `call` 互斥；三者都没有时必须给 `goto`。

执行顺序：`goto → call/action → wait → expect`。`retry` 是整步重试（重新 `goto`、重新匹配）。

```python
Step('open_deploy', click='arena_deploy_button', wait='arena_power_label')
Step('back_to_arena', click='arena_power_back', expect=lambda t: t.current_page() == 'arena')
Step('go_home', goto='home')
```

## 2. 动作

目标四形态（糖与完整写法共用）：

| 形态 | 示例 |
| --- | --- |
| 模板 | `'arena_deploy_button'` |
| 坐标 | `(0.87, 0.90)`（两分量 ≤1 为归一化） |
| 框 | `(120, 200, 300, 260)` |
| 运行时求值 | `lambda t: t.data['target'].center()` |

| 动作 | 参数 | 说明 |
| --- | --- | --- |
| `Click(target)` | target | 单击 |
| `DoubleClick(target, interval=0.12)` | target | 双击 |
| `RightClick(target)` | target | 右键；ADB 下等同单击 |
| `LongPress(target, hold=1.0)` | target | 触摸长按 |
| `Swipe(start, end, duration=0.5)` | 起止 | 匀速滑动，保留惯性 |
| `Drag(start, end, duration=0.6, hold=0.2)` | 起止 | 抬手前停住，无惯性 |
| `KeyPress(key, hold=0.02)` | key | `hold>0.15` 为长按 |
| `KeyCombo(keys, hold=0.05)` | keys | 组合键 |
| `InputText(text, target=None, settle=0.4)` | text | 先点目标再输入；Android 仅 ASCII |

糖只为「目标 + 默认参数」服务；需要改参数时写完整对象：

```python
Step('long_press_card', long_press='arena_card')                      # hold=1.0
Step('long_press_card', action=LongPress('arena_card', hold=1.5))     # 自定义
Step('scroll_list', action=Swipe((0.7, 0.75), (0.7, 0.4), duration=0.4))
```

## 3. 回调与 `data`

所有回调按 `f(task)` 调用，`t` 即当前任务实例（方法里的 `self`）。

| 位置 | 签名 | 时机 |
| --- | --- | --- |
| `call` | `f(task) -> Any` | 动作后、`wait` 前 |
| `expect` | `f(task) -> bool` | `wait` 后 |
| `when` ✅ | `f(task) -> bool` | 执行前 |
| `Loop.until` ✅ | `f(task) -> bool` | 每轮结束 |
| `State.transitions` 守卫 | `f(task) -> bool` | 状态动作后，取第一个 True |
| `State.do=func` | `f(task) -> Any` | 进入状态时 |

`data` 规则：每次运行开始重建；`call` 返回值以**步骤名**为键、`State.do` 返回值以**状态名**为键；嵌套调用只清空内层。

```python
Step('read_entries', call=self.read_entries)          # data['read_entries'] = (10, 10)
Step('check', expect=lambda t: t.data['read_entries'][0] > 0)
```

`expect` 里不要改数据（重试会叠加副作用）；`until` 里不要做 OCR（每轮都执行）。

## 4. 驱动器

### 4.1 Flow

```python
Flow(steps, final=[...])     # final ✅
```

顺序执行；任一步失败即停（除非 `optional`/`skip`）；`final` 无论成功失败都执行。

### 4.2 StateMachine

```python
StateMachine(states, start=None, max_transitions=50, final=[...])   # final ✅
State(name, goto='', do=Step | [Step] | Flow | func, transitions=[(guard, target), ...])
```

进入状态 → 执行 `do` → 按顺序求值守卫 → 跳转；守卫全不命中即结束；超出 `max_transitions` 抛错。

```python
return StateMachine({
    'at_arena': State('at_arena', goto='arena',
                      do=[Step('refresh_entries', call=self.read_entries)],
                      transitions=[(lambda t: t.data['refresh_entries'][0] > 0, 'pick'),
                                   (lambda t: True, 'finish')]),
    'pick':     State('pick', do=[Step('pick_target', call=self.pick_target)],
                      transitions=[(lambda t: t.data['pick_target'] is None, 'no_target'),
                                   (lambda t: True, 'battle')]),
    'battle':   State('battle', do=self.battle_steps,
                      transitions=[(lambda t: True, 'at_arena')]),
    'no_target': State('no_target', do=Stop('no target')),
    'finish':    State('finish',    do=Stop('no entries')),
}, start='at_arena', max_transitions=36, final=[Step('go_home', goto='home')])
```

判定点建议单独成状态：把「剩余次数」「是否找到目标」分别放在 `at_arena`、`pick` 的出边上，而不是塞进一个 `until`。

### 4.3 Loop

```python
Loop(steps, until=lambda t: bool, times=3, on_exhausted='abort')      # ✅
```

每轮执行 `steps`，`until` 为 True 退出；`until=None` 固定跑 `max` 轮。

```python
Loop([Step('pick_target', call=self.pick_target),
      Step('scroll_list', action=Swipe((0.7, 0.75), (0.7, 0.4)))],
     until=lambda t: t.data['pick_target'] is not None, max=4)
```

`Loop` 与状态机：判定点只有一个、流程固定用 `Loop`；判定点会变多或状态要被别的流程复用时用状态机。

### 4.4 final / Stop / when

| 工具 | 作用 |
| --- | --- |
| `final=[...]` ✅ | 无论成功/失败/异常都执行 |
| `Stop('reason')` ✅ | 主动结束（抛 `FlowAborted`），`final` 仍执行 |
| `step.stop_if(cond, 'reason')` ✅ | 在 `call` 里主动结束 |
| `Step(when=guard)` ✅ | 条件跳过，不算失败 |

## 5. 任务调用

```python
class BattleTask(CallableTask):          # ✅
    SKIP_GAME_BOOTSTRAP = True

    def execute(self, origin: str = 'arena', timeout: float = 180.0) -> BattleResult:
        return self.battle.fight(origin=origin, timeout=timeout)
```

```python
Step('fight', click='arena_vs_battle', call=lambda t: t.call_task(BattleTask, origin='arena'))
```

| 项 | 说明 |
| --- | --- |
| `execute(...)` | 唯一业务方法，签名即参数表，`return` 即返回值 |
| `call_task(Target, **kwargs)` | 同步调用，返回 `execute` 的返回值 |
| `helper_tasks` | 只实例化，不进 GUI / MCP 列表 |
| 嵌套 | 重入直接报错，深度上限 3，内层跳过启动层并共享 `last_page` |

## 6. 常见写法

| 需求 | 写法 |
| --- | --- |
| 重试本步 | `Step('x', click='a', retry=2)` |
| 失败可忽略 | `Step('x', click='a', optional=True)` |
| 条件执行 ✅ | `Step('x', click='a', when=lambda t: t.data['flag'])` |
| 读数据 | `Step('read', call=self.read_entries)` |
| 动态点击 | `Step('pick', click=lambda t: t.data['target'].center())` |
| 两页来回 | `Step('a', goto='arena')` / `Step('b', goto='home')` |
| 成功/失败分流 | 状态机两条守卫 |
| 固定次数重复 ✅ | `Loop([...], max=3)` |
| 条件重复 ✅ | `Loop([...], until=lambda t: t.data['done'])` |

## 7. 常见错误

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `FlowConfigError` | 只写了 `name` | 补 `goto` 或动作 |
| 分支没生效 | 用 `expect` 当 if | 改用状态机守卫 |
| `expect` 一直 False | 条件写成了动作前的状态 | 它在动作与 `wait` 之后 |
| 点不到目标 | 模板匹配失败 | 检查模板命名分辨率与 `roi` |
| 找不到失败截图 | 该步是 `optional` | 只有 `abort` 截图 |
| 状态机「没有进展」 | 守卫恒真且状态不变 | 检查守卫依赖的数据 |
| 任务卡死 | 守卫永不满足 | 设 `max_transitions` / `max` |

## 8. 平台差异

| 动作 | Android (adb) | Windows (post_message / pynput / pydirect) |
| --- | --- | --- |
| `Click` / `DoubleClick` / `RightClick` | `click` / `click(key='right')` | 同名方法均有 |
| `Swipe` | `swipe` | 有 |
| `LongPress` | `motionevent DOWN/UP` | `mouse_down` + sleep + `mouse_up` |
| `Drag` | `motionevent` 分段 | `mouse_down` → move → hold → `mouse_up` |
| `KeyPress` / `KeyCombo` | `send_key` / `send_key_down+up` | 有 |
| `InputText` | `input text`，仅 ASCII | `input_text`，pynput 支持 Unicode |
