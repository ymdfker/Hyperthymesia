"""内部任务的进程边界：只标记后台子进程，不改变正常前台的环境。"""
import os

INTERNAL_ENV = 'HYPERTHYMESIA_INTERNAL_CALL'


def internal_env(env=None):
    """所有内部 CLI 调用及其子进程继承同一个标记。"""
    result = dict(os.environ if env is None else env)
    result[INTERNAL_ENV] = '1'
    return result


def is_internal():
    return os.environ.get(INTERNAL_ENV) == '1'


def is_writer_workdir(cwd):
    """写入器自己的空工作目录。有的宿主（如 WorkBuddy、Qoder 桌面端）启动钩子时不继承环境变量，
    只能再按目录排除，避免写入器会话被当成用户对话抓回（自我循环）。"""
    if not cwd: return False
    from . import paths
    try:
        base = os.path.normcase(os.path.realpath(str(paths.home() / 'writer_work')))
        here = os.path.normcase(os.path.realpath(str(cwd)))
    except (OSError, ValueError):
        return False
    return here == base or here.startswith(base + os.sep)
