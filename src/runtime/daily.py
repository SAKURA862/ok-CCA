"""跨日判定：游戏以本地时间 04:00 作为「新的一天」。

不是自然日零点——公告、签到、日常重置都发生在 04:00，所以：
03:30 仍算前一天，04:01 才是新的一天。

状态写在 ``<config_folder>/daily_state.json``：

```json
{"last_run_day": "2026-11-03"}
```

任务只需要问两件事：:meth:`DailyState.is_pending` 今天要不要做每日弹窗处理，
:meth:`DailyState.mark_done` 做完后把日期写回去。
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

DAY_START_HOUR = 4
STATE_FILE = 'daily_state.json'


def game_day(now: datetime | None = None) -> date:
    """把当前时刻换算成「游戏日」（04:00 之前算前一天）。"""
    current = now or datetime.now()
    return (current - timedelta(hours=DAY_START_HOUR)).date()


class DailyState:
    """每日状态的最小实现，容忍文件缺失与损坏。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    # ------------------------------------------------------------------ 读写
    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding='utf-8') or '{}')
        except Exception:
            return {}

    def _write(self, data: dict) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8'
            )
        except Exception:
            # 状态写不进去只影响「今天是否重复处理弹窗」，不该中断任务
            pass

    # ------------------------------------------------------------------ 查询
    @property
    def last_run_day(self) -> str:
        return str(self._read().get('last_run_day') or '')

    def is_pending(self, now: datetime | None = None) -> bool:
        """今天（按 04:00 划分）还没有处理过每日弹窗。"""
        return self.last_run_day != game_day(now).isoformat()

    def mark_done(self, now: datetime | None = None) -> None:
        data = self._read()
        data['last_run_day'] = game_day(now).isoformat()
        self._write(data)


def state_of(task) -> DailyState:
    """按任务的 ``config_folder`` 找到状态文件，取不到就退回当前目录。"""
    config = getattr(getattr(task, 'executor', None), 'config', None) or {}
    folder = config.get('config_folder') or 'configs'
    return DailyState(Path(folder) / STATE_FILE)
