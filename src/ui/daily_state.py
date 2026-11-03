"""一键日常的持久化状态。

只做两件事：
1. 记住哪些任务被加入了「一键日常」（configs/DailyPlan.json）。
2. 记住今天哪些任务已经完成（configs/DailyStatus.json），跨天自动清空。
"""

from datetime import date

from PySide6.QtCore import QObject, Signal

from ok import Config

# 加入一键日常的任务 key 列表
PLAN = Config('DailyPlan', {'selected': []})
# 今日完成情况：{'date': 'YYYY-MM-DD', 'done': [task_key, ...]}
STATUS = Config('DailyStatus', {'date': '', 'done': []})


class DailySignals(QObject):
    """一键日常状态变化时通知所有页面刷新。"""

    changed = Signal()


signals = DailySignals()


def task_key(task) -> str:
    cls = task.__class__
    return f'{cls.__module__}.{cls.__name__}'


def today() -> str:
    return date.today().isoformat()


def _selected() -> list:
    return list(PLAN.get('selected') or [])


def _done() -> list:
    if STATUS.get('date') != today():
        STATUS['date'] = today()
        STATUS['done'] = []
    return list(STATUS.get('done') or [])


def is_in_daily(task) -> bool:
    return task_key(task) in _selected()


def set_in_daily(task, value: bool):
    key = task_key(task)
    selected = _selected()
    changed = False
    if value and key not in selected:
        selected.append(key)
        changed = True
    elif not value and key in selected:
        selected.remove(key)
        changed = True
    if changed:
        PLAN['selected'] = selected
        signals.changed.emit()


def completed_today(task) -> bool:
    return task_key(task) in _done()


def mark_done(task):
    key = task_key(task)
    done = _done()
    if key not in done:
        done.append(key)
        STATUS['date'] = today()
        STATUS['done'] = done
        signals.changed.emit()


def mark_undone(task):
    key = task_key(task)
    done = _done()
    if key in done:
        done.remove(key)
        STATUS['done'] = done
        signals.changed.emit()


def selected_tasks(tasks):
    selected = _selected()
    return [task for task in tasks if task_key(task) in selected]


def remaining_tasks(tasks):
    done = _done()
    return [task for task in selected_tasks(tasks) if task_key(task) not in done]


def reset_today():
    STATUS['date'] = today()
    STATUS['done'] = []
    signals.changed.emit()
