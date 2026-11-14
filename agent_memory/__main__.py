"""打包后单一可执行文件的入口：agent-memory <子命令> ...
各子命令随对应模块移植逐步加入（设计 27.2）。"""
import sys
from . import __version__

COMMANDS = {}   # 子命令名 -> (处理函数(argv), 一行说明)；serve、hook、write、install、doctor 在后续步骤加入


def _serve(argv):
    from .mcp_server import serve
    return serve(argv)


def _context(argv):
    """调试用：打印当前目录下本轮会注入的记忆文本（不记送达）。"""
    import os
    from . import reader
    from .mcp_server import open_stores
    print(reader.context(open_stores(argv[0] if argv else os.getcwd())) or '（无注入内容）')


COMMANDS['serve'] = (_serve, '启动 MCP 只读服务（stdio）')


def _hook(argv):
    from .hooks import run
    return run(argv)


def _write(argv):
    from .writecmd import run
    return run(argv)


def _install(argv):
    from .install import run
    return run(argv)


def _uninstall(argv):
    from .install import run
    return run(argv, remove=True)


COMMANDS['hook'] = (_hook, '钩子入口：hook <prompt-submit|stop|pre-compact|session-start|session-end> --agent <claude|codex>')
COMMANDS['write'] = (_write, '写入积压的已完成轮次：write [--project 目录]')
COMMANDS['install'] = (_install, '给 agent 写入 MCP 与钩子配置：install <claude|codex> [--project 目录]')
COMMANDS['uninstall'] = (_uninstall, '移除本框架写入的配置：uninstall <claude|codex> [--project 目录]')
COMMANDS['context'] = (_context, '打印当前目录会注入的记忆（调试用）')


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ('-h', '--help', 'help'):
        print('agent-memory %s\ncommands:' % __version__)
        for n, (_, h) in sorted(COMMANDS.items()): print('  %-10s %s' % (n, h))
        return 0
    if argv[0] in ('-V', '--version'):
        print(__version__); return 0
    if argv[0] not in COMMANDS:
        print('未知子命令：%s' % argv[0], file=sys.stderr); return 2
    return COMMANDS[argv[0]][0](argv[1:]) or 0


if __name__ == '__main__':
    sys.exit(main())
