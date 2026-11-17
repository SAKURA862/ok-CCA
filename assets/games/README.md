# 游戏接入口径（`assets/games/*.json`）

一份 JSON 就是一次游戏接入，不需要写 Python：

```json
{
  "name": "示例游戏",
  "package": "com.example.demo",
  "launch": { "kind": "android_app" },
  "stop": { "kind": "force_stop" },
  "login": { "template": "demo_start" },
  "ready": { "template": "demo_home" }
}
```

- 文件名即 `game_profile`：`crosscore.json` → 任务里写 `game_profile = 'crosscore'`。
- `launch.kind`：`android_app`（`monkey` 拉起）/ `desktop_exe`（需同时给 `launch.command`）/ `none`。
- `stop.kind`：`force_stop`（`am force-stop`）/ `none`。
- `login.template`：登录页锚点，同时作为点击目标（点它的中心）。
- `ready.template`：进入游戏后的主界面锚点；留空表示「启动即就绪」。
- 模板文件放在 `assets/templates/`，命名 `<名字>_<宽>x<高>_<x>_<y>.png`，宽高写**截图分辨率**。

仓库里自带的 `crosscore.json` 是当前测试用游戏的配置（交错战线），换成别的游戏时复制一份改字段即可；只有 JSON 表达不了的情况（登录要滑动、要点两个按钮）才写 `src/games/<profile>.py` 覆写方法。

## 临时说明（P1 冒烟期）

`crosscore.json` 的 `ready.template` 目前指向 **`nav_lobby_anchor`（大厅「公告」弹窗左上角的「公告」二字）**，
仅用于 P1 生命周期冒烟——因为大厅底部导航锚点会被全屏弹窗的半透明遮罩穿透，而「出击」按钮在遮罩下相关性掉到阈值以下。

P2 弹窗层完成后再替换回正常的大厅锚点（如「出击」/底部导航），并做 P1×P2 联调测试。
