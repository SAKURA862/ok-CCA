# 任务实现模型与期待功能

本文是「任务怎么写、框架替你做什么」的权威说明。所有示例与字段以当前实现为准
（`src/flow/`、`src/nav/`、`src/runtime/`、`src/tasks/MyBaseTask.py`）。

## 0. 一句话

任务 = **声明式步骤流**。开发者只描述「这一步点哪里、等什么、读出什么、分叉去哪」；
框架负责「保证游戏已启动、保证画面干净、保证站在正确页面、等待与重试」。

## 1. 分层

| 层 | 位置 | 负责 | 不负责 |
| --- | --- | --- | --- |
| 入口层 | GUI / CLI / MCP | 触发 `run()`、展示日志与进度 | 任何页面细节 |
| 任务层 | `MyBaseTask`、`CallableTask` | 配置、数据白板、调用其他任务 | 具体点击坐标 |
| 编排层 | `Flow` / `StateMachine` / `Loop` / `Step` | 顺序、分支、重复、等待与重试 | 手指怎么动 |
| 动作层 | `src/flow/actions.py` | 点击 / 长按 / 滑动 / 拖拽 / 按键 / 文本 | 页面识别 |
| 导航层 | `src/nav/` | 页面图、定位、寻路、跳转与校验 | 业务语义 |
| 弹窗层 | `src/runtime/overlay.py` | 任意弹窗拦截（挂在 `next_frame()`） | 任务流程 |
| 启动层 | `src/tasks/bootstrap.py` | 未启动则启动、停在登录页则点掉 | 任务流程 |
| 设备层 | ok-script | 截图、匹配、OCR、ADB 输入 | 业务决策 |

## 2. Step：一步是什么

```python
Step(name, goto=None, when=None,
     action=None, click=None, double_click=None, right_click=None,
     long_press=None, key_press=None, call=None,
     wait=None, wait_timeout=8.0, expect=None,
     retry=1, on_fail='abort', optional=False)
```

| 字段 | 含义 |
| --- | --- |
| `name` | 唯一的步骤名；日志键、`task.data` 的键、失败截图名 |
| `goto` | 动作前先 `ensure_page(goto)`，幂等 |
| `when` | 守卫函数，返回 False 时整步跳过（不算失败） |
| `action` | 动作对象，如 `Click('x')`、`Swipe(...)` |
| `click` 等五个 | 语法糖，分别等价于 `Click/DoubleClick/RightClick/LongPress/KeyPress` |
| `call` | 观察/计算函数，返回值写入 `task.data[name]` |
| `wait` | 动作后必须出现的模板；**可给多个，任一出现即成功** |
| `wait_timeout` | 单次观察窗口（秒），默认 **2**；命中即返回 |
| `expect` | 额外断言，返回 False 视为失败（**不是分支**） |
| `retry` | 整步重试次数，默认 **5**；`attempts = retry + 1` |
| `on_fail` | 用尽重试后：`retry` / `skip` / `abort` |
| `optional` | 可选步骤，失败只记警告并继续 |

执行顺序：`when` → `goto` → 动作 → `wait` → `expect` → 成功，否则重试。

要点：

- `retry` 重做的是**整步**（重新匹配模板、重新点击、重新等待），不是只重等。
- `wait` 的判据应是「可交互元素出现」（按钮），而不是背景锚点——半透明遮罩下背景仍会命中。
- `expect` 是断言；胜负、分支请用 `StateMachine`。


### 失败分类（重要）

| 类型 | 判定 | 是否重试 |
| --- | --- | --- |
| 目标缺失 | 动作目标（模板/坐标）未命中 | **否**，立即失败并截图 `missing_<模板>` |
| 等待超时 | 点击后 `wait` 模板在窗口内未出现 | 是，最多 `retry` 次 |
| 断言失败 | `expect` 返回 False | 是 |

有副作用的操作（购买、挑战、消耗次数）请显式写 `retry=0` 或 `retry=1`，
靠 `wait_timeout` 争取时间，避免重复点击造成多次成交。
## 3. 动作层

目标（target）三选一：

```python
Click('arena_challenge_button')      # 模板名
Click((0.665, 0.916))                # 归一化坐标
Click((0.5, 0.5, 0.2, 0.1))          # 归一化框，点框中心
LongPress('opponent_card', hold=1.2) # 模板 + 长按
LongPress(lambda t: t.data['p'].center())  # 动态坐标
```

动作清单：`Click`、`DoubleClick`、`RightClick`、`LongPress`、`Swipe`、`Drag`、
`KeyPress`、`KeyCombo`、`InputText`。

| 糖写法 | 等价 |
| --- | --- |
| `click='x'` / `click=(x, y)` | `Click('x')` / `Click((x, y))` |
| `double_click=...` | `DoubleClick(...)` |
| `right_click=...` | `RightClick(...)` |
| `long_press=...` | `LongPress(...)`，`hold=1.0` |
| `key_press='esc'` | `KeyPress('esc')` |

平台差异：ADB 下 `RightClick` 等同普通点击；`Drag` 依次尝试 `motionevent`、
鼠标事件、`swipe`；`InputText` 仅 ASCII。

## 4. 驱动器

```python
Flow(steps, final=None)                       # 顺序；允许 Step / Stop / Loop
StateMachine(states, final=None, max_transitions=50)
State(name, goto=None, do=None, transitions=[(guard, target), ...])
Loop(steps, until=None, times=10, on_exhausted='abort', final=None)
```

容器契约（**不要放宽**）：

| 容器 | 允许的内容 |
| --- | --- |
| `Flow.steps` | `Step` / `Stop` / `Loop` |
| `State.do` | `Step` / `Stop` / `Flow`（列表时同上） |
| `Loop.steps` | `Step` / `Stop` |

状态内确实需要重复时，写成 `do=Flow([Loop([...])])`，而不是让 `State` 认识 `Loop`。

`final` 在正常结束与异常退出时都会执行（异常时收尾失败只告警），适合「回主页」。

## 5. 任务调用任务

```python
class ArenaBattle(CallableTask):
    SKIP_GAME_BOOTSTRAP = True

    def execute(self, row: int = 0) -> dict:
        ...
        return {'outcome': 'win'}
```

```python
result = self.call_task(ArenaBattle, row=2)   # 同步、阻塞、返回 execute 的返回值
```

语义：深度上限 3；内层不重复启动层；共享 `last_page`；每次调用清空内层
`data`/`result`；异常包装成 `TaskCallError('<外层> -> <内层>: ...')` 并截图；
`config['helper_tasks']` 里注册的任务只实例化能力，**不出现在 GUI/MCP 任务列表**。

分工示例（竞技场）：子任务负责「挑对手 → 挑战 → 判胜负 → 回到竞技场」，
父任务负责「关获得物品弹窗、读次数、决定下一轮」。

## 6. 等待与重试哲学（关键）

1. **不用固定 `sleep` 等 UI**。`sleep` 只做冷却。
2. 一切等待 = 条件轮询 + 超时，由框架提供：`wait_until` / `Step.wait` / `Step.retry`。
3. 动画吞点击这类问题，标准解法就是一个 Step：
   `Step('finish_battle', click=(0.5, 0.62), wait='arena_deploy_button', wait_timeout=3.0, retry=8)`
   语义是「点一次 → 3 秒内等到目标出现 → 否则整步重试」。
4. `Loop` 只用于真正的重复（打 N 场、刷到次数为 0），**不用于等待重试**。
5. 判断「页面就绪」用可交互锚点；不要用背景锚点。

## 7. 责任边界

| 谁 | 负责 |
| --- | --- |
| 框架 | 启动、弹窗、导航、编排、等待重试、日志、截图、异常恢复 |
| 开发者 | 页面图 JSON、模板采集、步骤与分叉、数据解析与业务判断 |
| 框架不提供 | 具体游戏的战斗实现、战利品策略（规划在 P3.7 / P3.8） |

## 8. 现状

已实现：导航层（P3）、编排层（P3.5）、动作层（P3.5.1）、任务调用任务（P3.6）、
弹窗层（P2）、启动层（P1）、日志与底边栏（独立提交）。

当前缺口：

- `wait` 传数组与 `wait_timeout` 缺少单测；
- `recover_to_home`（异常后回到主页的通用恢复）尚未提供；
- 战斗、扫荡、战利品属 P3.7 / P3.8，尚未开始。
