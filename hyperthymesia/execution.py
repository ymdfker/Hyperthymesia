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
