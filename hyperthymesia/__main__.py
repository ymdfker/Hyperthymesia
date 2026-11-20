"""打包后单一可执行文件的入口：hyperthymesia <子命令> ...
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
    if '--agent' in argv:   # 按某个 agent 检查：与钩子里一样把它当宿主，看整理记忆会用谁的模型
        a = argv[argv.index('--agent') + 1]
        if a == 'workbuddy':
            from .install import workbuddy_config_dir
            directory = str(workbuddy_config_dir())
            os.environ['CODEBUDDY_CONFIG_DIR'] = directory
            os.environ['WORKBUDDY_CONFIG_DIR'] = directory
        os.environ['HYPERTHYMESIA_HOST_AGENT'] = 'codebuddy' if a == 'workbuddy' else a
    s = config.writer_settings()
    print('记忆目录：%s' % paths.home())
    print('写入提供方：%s（来源：%s）' % (s['provider'] or '无', s['source']))
    if s['provider'] in config.CLI_EXE:
        from . import providers
        try:
            cmd = providers.codebuddy_cmd() if s['provider'] == 'codebuddy' else providers.qodercli_cmd() if s['provider'] == 'qoder' else [shutil.which(config.CLI_EXE[s['provider']])]
            print('  命令行入口：%s' % (' '.join(cmd) if cmd and all(cmd) else '未找到'))
            if '--check-cli' in argv and cmd and all(cmd):
                rep = providers._run_cli(cmd + ['--version'], agent=s['provider'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=20)
                if rep.returncode: print('  启动失败：%s' % providers._failure_hint(rep.stderr or rep.stdout))
                else: print('  启动检查：通过（--version，不调用模型）')
        except Exception as exc: print('  命令行不可用：%s' % providers._failure_hint(exc))
        print('  鉴权及真实写入：尚未验证；桌面已登录不代表CLI可调用，不会自动花额度试探。')
        print('  若 write 报“宿主CLI鉴权失败”（如 WorkBuddy Windows lite 构建）：改用自己的OpenAI兼容API，'
              '在 %s 写 [writer] provider="openai"、model、base_url、api_key_env，再运行本命令确认 key 已读到。' % (paths.home() / 'config.toml'))
    from .store import state
    st = state(paths.home())
    try: pending = st.execute('SELECT SUM(completed_at IS NULL), SUM(completed_at IS NOT NULL) FROM backlog WHERE written=0').fetchone()
    finally: st.close()
    print('待处理：已完成%d轮，未完成%d轮（不会把未完成轮次冒充完成）' % (pending[1] or 0, pending[0] or 0))
    if s['provider'] == 'openai':
        key, var = config.api_key(s)
        print('  接口地址：%s' % (s['base_url'] or 'https://api.openai.com/v1'))
        print('  模型：%s' % (s['model'] or '未配置（必填）'))
        print('  key：%s' % ('已从环境变量 %s 读到（不显示内容）' % var if key else '环境变量 %s 未设置' % var))
    elif s['model']:
        print('  模型：%s（用户明确指定，跳过自动准入；不代表质量已验收）' % s['model'])
    elif s['provider'] in ('codex', 'claude', 'codebuddy', 'qoder', 'dsh'):
        from . import models
        print('  模型：%s' % models.explain(s['provider']))
    if '--agent' not in argv:
        print('提示：在 agent 里使用时，整理记忆用的是该 agent 自己的模型；查看某个 agent 的情况：hyperthymesia doctor --agent 名字')
    return 0 if s['provider'] else 1


COMMANDS['doctor'] = (_doctor, '自检配置及积压（不显示key）；--agent X，--check-cli无模型检查启动')
def _import(argv):
    from .importer import run
    return run(argv)


COMMANDS['import'] = (_import, '导入接入前已有的会话：import --list | --agent X --session ID... | --agent X --all [--days N]')
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
        print('hyperthymesia %s\ncommands:' % __version__)
        for n, (_, h) in sorted(COMMANDS.items()): print('  %-10s %s' % (n, h))
        return 0
    if argv[0] in ('-V', '--version'):
        print(__version__); return 0
    if argv[0] not in COMMANDS:
        print('未知子命令：%s' % argv[0], file=sys.stderr); return 2
    return COMMANDS[argv[0]][0](argv[1:]) or 0


if __name__ == '__main__':
    sys.exit(main())
