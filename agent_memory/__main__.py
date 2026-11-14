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


def _doctor(argv):
    """自检：写入模型从哪里来、能不能用；不打印任何 key 的内容。"""
    import os, shutil
    from . import config, paths
    s = config.writer_settings()
    print('记忆目录：%s' % paths.home())
    print('写入提供方：%s（来源：%s）' % (s['provider'] or '无', s['source']))
    if s['provider'] in config.CLI_EXE:
        exe = shutil.which(config.CLI_EXE[s['provider']])
        print('  命令行：%s' % (exe or '未找到（请安装或在配置里换提供方）'))
    if s['provider'] == 'openai':
        key, var = config.api_key(s)
        print('  接口地址：%s' % (s['base_url'] or 'https://api.openai.com/v1'))
        print('  模型：%s' % (s['model'] or '未配置（必填）'))
        print('  key：%s' % ('已从环境变量 %s 读到（不显示内容）' % var if key else '环境变量 %s 未设置' % var))
    elif s['model']:
        print('  模型：%s' % s['model'])
    return 0 if s['provider'] else 1


COMMANDS['doctor'] = (_doctor, '自检：写入模型配置是否可用（不显示 key）')
COMMANDS['hook'] = (_hook, '钩子入口：hook <prompt-submit|stop|pre-compact|session-start|session-end> --agent <claude|codex>')
COMMANDS['write'] = (_write, '写入积压的已完成轮次：write [--project 目录]')
COMMANDS['install'] = (_install, '给 agent 写入 MCP 与钩子配置：install <claude|codex> [--project 目录]')
COMMANDS['uninstall'] = (_uninstall, '移除本框架写入的配置：uninstall <claude|codex> [--project 目录]')
COMMANDS['context'] = (_context, '打印当前目录会注入的记忆（调试用）')


def _utf8_stdio():
    """Windows 的标准输入输出默认是本地代码页，宿主和 MCP 客户端传的是 UTF-8：统一改成 UTF-8。"""
    for s in (sys.stdin, sys.stdout, sys.stderr):
        try: s.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError): pass


def main(argv=None):
    _utf8_stdio()
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
