"""打包后单一可执行文件的入口：agent-memory <子命令> ...
各子命令随对应模块移植逐步加入（设计 27.2）。"""
import sys
from . import __version__

COMMANDS = {}   # 子命令名 -> (处理函数(argv), 一行说明)；serve、hook、write、install、doctor 在后续步骤加入


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
