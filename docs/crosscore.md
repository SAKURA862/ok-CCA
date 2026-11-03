# 交错战线：启动游戏

「交错战线·一键日常」目前只做第一步：**把游戏启动起来并进入游戏**。启动逻辑本身不是独立任务，抽在
`src/tasks/CrossCoreLauncher.py` 里，任何需要游戏在前台的任务都可以直接调用。

## 运行方式

GUI：首页任务卡片或「任务设定」里点「开始」，任务名「交错战线·一键日常」。

命令行（先关闭 GUI，ok-script 单实例互斥）：

```powershell
.\.venv\Scripts\python.exe -m ok run_task CrossCoreDailyTask --config src.config:config
```

MCP（GUI 以 `--mcp` 启动时）：

```powershell
$env:NO_PROXY='127.0.0.1,localhost'
.\.venv\Scripts\python.exe tools\mcp_cli.py task src\tasks\CrossCoreDaily.py --poll 300
```

## 每次运行做什么

| 阶段 | 行为 |
| --- | --- |
| `reset_to_start` | `am force-stop com.megagame.crosscore`，按 HOME 回到模拟器桌面，截图 `reset_home` |
| `verify_start_state` | 断言能读到前台应用，且游戏不在前台；否则抛错，不进入主流程 |
| `run` | 启动包名 → 轮询标题页 → 点击「开始游戏」→ 确认标题页消失 |

- GUI / CLI 调度器只调用 `run()`，因此 `run()` 在没有执行过恢复时会自己补一次 `reset_to_start` + `verify_start_state`；
  MCP 运行器已经执行过这两个钩子，`run()` 就不重复。
- 所有等待都有上限：出现「开始游戏」最多等 `Launch Timeout (Seconds)`（默认 180 秒），点击后最多等 90 秒。
- 失败时保存 `failed_no_start_button` / `failed_stuck_on_title` / `failed_left_game` 截图（在 `screenshots/`，MCP 运行在 `logs/mcp/<run_id>/`）。
- 结束条件是可观察的：`开始游戏` 特征连续 5 次采样消失，且游戏仍在前台。

## 识别方式（不依赖 OCR）

标题页的「开始游戏」按钮是一块**水平居中、画面偏下的亮色带**。实现只做颜色分类 + 几何判定：

1. 把整帧缩到 320×180，取 `x∈[0.33,0.67]`、`y∈[0.60,0.73]` 的 ROI；
2. 统计「近白」像素比例，要求落在 `[0.008, 0.09]`，且亮行数 ≥ 3、亮块质心横向偏离中心 ≤ 0.08；
3. 满足即判定标题页，点击点固定取画面正中偏下 `(0.5, 0.668)`（按钮几何中心），避免被两侧装饰横线带偏。

这套判据在同一台模拟器上区分度很高：标题页 ROI 亮像素比例约 2.2%%，加载页与游戏内都是 0%。

## 输入方式

点击走 ok-script 的交互层，在当前 adb 采集模式下即 `adb shell input tap`（后台可用，不要求模拟器窗口在前台）。

PostMessage 后台输入**在本机没有验证通过**：MuMu 的窗口属于 Medium 完整性级别进程，而从本仓库的沙箱/子进程发出的
`PostMessage` 一律返回 `WinError 5 (拒绝访问)`；连计划任务抬升也没有改变调用方的 Low 完整性级别，因此无法给出结论。
如果后续要在非沙箱环境验证，可以按 ok-script 的窗口采集模式（`configs/devices.json` 的 `capture` 设为 `windows`、
`windows.interaction` 设为 `PostMessage`）再试，届时需要断言目标窗口确实收到了点击。

## 已知限制

- 只识别「开始游戏」按钮，不处理公告弹窗、账号登录、版本更新提示；如果游戏停在公告页，本步骤会判定为标题页未出现并失败。
- 标题页按钮位置是相对几何；更换分辨率或游戏改版后需要重新确认 `(0.5, 0.668)` 与 ROI。
- 「进入游戏」的判据是「标题页特征消失且游戏仍在前台」，没有区分登录后的大厅/活动页。
