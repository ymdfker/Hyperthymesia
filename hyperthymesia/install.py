"""hyperthymesia install/uninstall <agent>：给 agent 写入（或移除）MCP 服务与钩子配置。

原则：只增删本框架自己的条目，用户原有配置原样保留；改动前把原文件备份为 *.hyperthymesia.bak。
- claude：用户级 ~/.claude/settings.json 加钩子，~/.claude.json 的 mcpServers 加服务（--project 目录 时改为该项目的
  .claude/settings.local.json 和 .mcp.json）。
- codex：~/.codex/config.toml 末尾追加一段带标记的配置（--project 时为该项目的 .codex/config.toml）。
  Codex 的新钩子必须由用户在 Codex 里执行 /hooks 审核信任后才会运行，安装后会提示。"""
import json, os, shutil, sys
from pathlib import Path

from .hooks import self_cmd

NAME = 'hyperthymesia'
MARK_BEGIN = '# >>> hyperthymesia（由 hyperthymesia install 生成，uninstall 会删除这一段）'
MARK_END = '# <<< hyperthymesia'
CLAUDE_EVENTS = {'UserPromptSubmit': 'prompt-submit', 'Stop': 'stop', 'PreCompact': 'pre-compact', 'SessionStart': 'session-start', 'SessionEnd': 'session-end'}
CODEX_EVENTS = {'UserPromptSubmit': 'prompt-submit', 'Stop': 'stop', 'SessionStart': 'session-start'}


def _quote(a):
    return '"%s"' % a if (' ' in a or '\\' in a) else a


def _cmd(*args):
    return ' '.join(_quote(a) for a in self_cmd() + list(args))


def _backup(p):
    if p.exists():
        b = p.with_name(p.name + '.hyperthymesia.bak')
        if not b.exists(): shutil.copy2(p, b)


def _load(p):
    try: return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
    except ValueError: raise SystemExit('无法解析 %s，请先手动修复它' % p)


def _save(p, d):
    p.parent.mkdir(parents=True, exist_ok=True); _backup(p)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def _is_ours(h): return any(k in json.dumps(h) for k in (NAME, 'agent_memory', 'agent-memory'))   # 含旧名字：卸载能清掉改名前写入的条目


def claude(project=None, remove=False):
    home = Path(os.environ.get('HOME') or Path.home())
    sp = (Path(project) / '.claude' / 'settings.local.json') if project else home / '.claude' / 'settings.json'
    mp = (Path(project) / '.mcp.json') if project else home / '.claude.json'
    s = _load(sp); hooks = s.setdefault('hooks', {})
    for ev, name in CLAUDE_EVENTS.items():
        groups = [g for g in hooks.get(ev, []) if not _is_ours(g)]
        if not remove:
            groups.append({'hooks': [{'type': 'command', 'command': _cmd('hook', name, '--agent', 'claude'), 'timeout': 60}]})
        if groups: hooks[ev] = groups
        else: hooks.pop(ev, None)
    if not hooks: s.pop('hooks', None)
    _save(sp, s)
    m = _load(mp); servers = m.setdefault('mcpServers', {})
    servers.pop(NAME, None)
    if not remove:
        c = self_cmd(); servers[NAME] = {'type': 'stdio', 'command': c[0], 'args': c[1:] + ['serve'], 'env': {}}
    _save(mp, m)
    return [sp, mp]


def codex(project=None, remove=False):
    home = Path(os.environ.get('HOME') or Path.home())
    cp = (Path(project) / '.codex' / 'config.toml') if project else home / '.codex' / 'config.toml'
    text = cp.read_text(encoding='utf-8') if cp.exists() else ''
    if MARK_BEGIN in text:
        a = text.index(MARK_BEGIN); b = text.index(MARK_END, a) + len(MARK_END)
        text = (text[:a].rstrip('\n') + '\n' + text[b:].lstrip('\n')).strip('\n') + ('\n' if text.strip() else '')
    if not remove:
        c = self_cmd()
        block = [MARK_BEGIN, '[mcp_servers.%s]' % NAME, 'command = %s' % json.dumps(c[0]), 'args = %s' % json.dumps(c[1:] + ['serve'])]
        for ev, name in CODEX_EVENTS.items():
            block += ['', '[[hooks.%s]]' % ev, '[[hooks.%s.hooks]]' % ev, 'type = "command"',
                      'command = %s' % json.dumps(_cmd('hook', name, '--agent', 'codex')), 'timeout = 60']
        block.append(MARK_END)
        text = (text.rstrip('\n') + '\n\n' if text.strip() else '') + '\n'.join(block) + '\n'
    cp.parent.mkdir(parents=True, exist_ok=True); _backup(cp); cp.write_text(text, encoding='utf-8')
    return [cp]


def codebuddy_exe():
    """CodeBuddy 命令行：PATH 上的 codebuddy，或 WorkBuddy 安装包里自带的那一份。"""
    for c in [shutil.which('codebuddy'), '/Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/cli/bin/codebuddy',
              os.path.expandvars(r'%LOCALAPPDATA%\Programs\WorkBuddy\resources\app.asar.unpacked\cli\bin\codebuddy.cmd')]:
        if c and Path(c).exists(): return c
    return None


def codebuddy(project=None, remove=False):
    """CodeBuddy / WorkBuddy：钩子写 ~/.codebuddy/settings.json（--project 时为项目的 .codebuddy/settings.local.json）；
    MCP 用户级通过官方命令 `codebuddy mcp add --scope user` 登记，项目级写项目的 .mcp.json。"""
    home = Path(os.environ.get('HOME') or Path.home())
    sp = (Path(project) / '.codebuddy' / 'settings.local.json') if project else home / '.codebuddy' / 'settings.json'
    s = _load(sp); hooks = s.setdefault('hooks', {})
    for ev, name in CLAUDE_EVENTS.items():
        groups = [g for g in hooks.get(ev, []) if not _is_ours(g)]
        if not remove: groups.append({'hooks': [{'type': 'command', 'command': _cmd('hook', name, '--agent', 'codebuddy'), 'timeout': 60}]})
        if groups: hooks[ev] = groups
        else: hooks.pop(ev, None)
    if not hooks: s.pop('hooks', None)
    _save(sp, s); files = [sp]
    if project:
        mp = Path(project) / '.mcp.json'; m = _load(mp); servers = m.setdefault('mcpServers', {}); servers.pop(NAME, None)
        if not remove: c = self_cmd(); servers[NAME] = {'type': 'stdio', 'command': c[0], 'args': c[1:] + ['serve']}
        _save(mp, m); files.append(mp)
    else:
        import subprocess
        exe = codebuddy_exe()
        if not exe: raise SystemExit('找不到 codebuddy 命令行（WorkBuddy 安装包里自带一份）')
        subprocess.run([exe, 'mcp', 'remove', '--scope', 'user', NAME], capture_output=True)
        if not remove: subprocess.run([exe, 'mcp', 'add', '--scope', 'user', NAME, '--'] + self_cmd() + ['serve'], capture_output=True, check=True)
        files.append('codebuddy 用户级 MCP（经 codebuddy mcp add 登记）')
    return files


def qoder(project=None, remove=False):
    """Qoder（桌面 agent 与 qodercli 共用）：钩子写 ~/.qoder/settings.json（--project 时为项目的 .qoder/settings.local.json）；
    MCP 写 ~/.qoder/mcp.json（--project 时为项目的 .mcp.json）。"""
    home = Path(os.environ.get('HOME') or Path.home())
    sp = (Path(project) / '.qoder' / 'settings.local.json') if project else home / '.qoder' / 'settings.json'
    mp = (Path(project) / '.mcp.json') if project else home / '.qoder' / 'mcp.json'
    s = _load(sp); hooks = s.setdefault('hooks', {})
    for ev, name in CLAUDE_EVENTS.items():
        groups = [g for g in hooks.get(ev, []) if not _is_ours(g)]
        if not remove: groups.append({'hooks': [{'type': 'command', 'command': _cmd('hook', name, '--agent', 'qoder'), 'timeout': 60}]})
        if groups: hooks[ev] = groups
        else: hooks.pop(ev, None)
    if not hooks: s.pop('hooks', None)
    _save(sp, s)
    m = _load(mp); servers = m.setdefault('mcpServers', {}); servers.pop(NAME, None)
    if not remove: c = self_cmd(); servers[NAME] = {'command': c[0], 'args': c[1:] + ['serve']}
    _save(mp, m)
    return [sp, mp]


def _run_quiet(cmd, **kw):
    import subprocess
    try: return subprocess.run(cmd, capture_output=True, text=True, timeout=600, **kw)
    except (OSError, subprocess.SubprocessError): return None


def qoder_writer_check():
    """Qoder 桌面版不带命令行：写入要用 Qoder 自己的额度，需要官方 qodercli 并登录一次（不复用桌面版登录，已实测）。
    只在用户执行 install qoder 时检查；没装就直接默认安装（用户要求），不用 Qoder 的用户永远不会装它。返回给用户看的提示。"""
    exe = shutil.which('qodercli')
    if not exe:
        npm = shutil.which('npm')
        if npm:
            print('正在安装 Qoder 官方命令行 qodercli（npm 包 @qoder-ai/qodercli），用于以 Qoder 额度整理记忆……')
            _run_quiet([npm, 'install', '-g', '@qoder-ai/qodercli']); exe = shutil.which('qodercli')
        if not exe:
            return ('未能安装 qodercli（需要 npm）：记忆可以读取，但写入无法使用 Qoder 额度。可手动执行 npm install -g @qoder-ai/qodercli，'
                    '然后 qodercli login；或在 ~/.hyperthymesia/config.toml 里配置自己的 API key。')
    from .providers import qodercli_cmd
    r = _run_quiet((qodercli_cmd() or [exe]) + ['status', '--output', 'json'])
    try: st = json.loads(r.stdout or '{}') if r else {}
    except ValueError: st = {}
    if not st.get('logged_in'):
        return '还需要登录一次：执行 qodercli login（浏览器授权），之后写入会自动使用你的 Qoder 额度。'
    return 'qodercli 已登录：写入将使用你的 Qoder 额度。'


def traecli_path():
    """TRAE 官方命令行：PATH 上的 traecli，或官方安装脚本的默认位置 ~/.local/bin/traecli。"""
    p = shutil.which('traecli') or str(Path(os.environ.get('HOME') or Path.home()) / '.local' / 'bin' / 'traecli')
    return p if Path(p).exists() else None


def trae_writer_check():
    """Trae 桌面版不带命令行：写入要用 Trae 自己的额度，需要官方 TRAE CLI（traecli）。只在 install trae 时检查，没装就默认安装。"""
    if not traecli_path():
        print('正在安装 TRAE 官方命令行 traecli（官方安装脚本 trae.cn/trae-cli/install.sh），用于以 Trae 额度整理记忆……')
        if os.name == 'nt':
            _run_quiet(['powershell', '-NoProfile', '-Command', 'irm https://trae.cn/trae-cli/install.ps1 | iex'])
        else:
            # 把安装目录预先放进 PATH：官方脚本发现已在 PATH 中就不会改写用户的 shell 配置文件；本框架按绝对路径调用它
            env = dict(os.environ, PATH=str(Path(os.environ.get('HOME') or Path.home()) / '.local' / 'bin') + os.pathsep + os.environ.get('PATH', ''))
            _run_quiet(['sh', '-c', 'curl -fsSL https://trae.cn/trae-cli/install.sh | bash'], env=env)
        if not traecli_path():
            return '未能安装 traecli：记忆可以读取，但写入无法使用 Trae 额度。可手动安装（见 docs.trae.cn/cli），或在配置里使用自己的 API key。'
    r = _run_quiet([traecli_path(), 'models', '--json'])
    if not r or not (r.stdout or '').strip() or r.stdout.strip() in ('[]', 'null'):
        return '还需要登录一次：在终端运行 traecli，按提示登录 Trae 账号（之后写入会自动使用你的 Trae 额度）。'
    return 'traecli 可用：写入将使用你的 Trae 额度。'



TRAE_EVENTS = {'UserPromptSubmit': 'prompt-submit', 'Stop': 'stop', 'SessionStart': 'session-start'}   # Trae 没有压缩前、会话结束事件


def trae(project=None, remove=False):
    """Trae / Trae CN：钩子写 ~/.trae-cn/hooks.json（国际版 ~/.trae/hooks.json；--project 时为项目的 .trae/hooks.json）；
    MCP 写应用数据目录下 User/mcp.json（--project 时为项目的 .trae/mcp.json）。
    Trae 的钩子写入后还需用户在“设置 → Hooks”里打开开关才会运行。"""
    home = Path(os.environ.get('HOME') or Path.home())
    cn = (home / '.trae-cn').exists()
    hp = (Path(project) / '.trae' / 'hooks.json') if project else home / ('.trae-cn' if cn else '.trae') / 'hooks.json'
    if project: mp = Path(project) / '.trae' / 'mcp.json'
    elif os.name == 'nt': mp = Path(os.environ.get('APPDATA', str(home))) / ('Trae CN' if cn else 'Trae') / 'User' / 'mcp.json'
    else: mp = home / 'Library' / 'Application Support' / ('Trae CN' if cn else 'Trae') / 'User' / 'mcp.json'
    s = _load(hp); hooks = s.setdefault('hooks', {})
    for ev, name in TRAE_EVENTS.items():
        groups = [g for g in hooks.get(ev, []) if not _is_ours(g)]
        if not remove: groups.append({'hooks': [{'type': 'command', 'command': _cmd('hook', name, '--agent', 'trae'), 'timeout': 60}]})
        if groups: hooks[ev] = groups
        else: hooks.pop(ev, None)
    if not hooks: s.pop('hooks', None)
    _save(hp, s)
    m = _load(mp); servers = m.setdefault('mcpServers', {}); servers.pop(NAME, None)
    if not remove: c = self_cmd(); servers[NAME] = {'command': c[0], 'args': c[1:] + ['serve']}
    _save(mp, m)
    return [hp, mp]


AGENTS = {'trae': trae, 'claude': claude, 'codex': codex, 'workbuddy': codebuddy, 'codebuddy': codebuddy, 'qoder': qoder}   # workbuddy 与 codebuddy 同一套（WorkBuddy 底层是 CodeBuddy）


def run(argv, remove=False):
    """hyperthymesia install|uninstall <claude|codex> [--project 目录]"""
    if not argv or argv[0] not in AGENTS:
        print('用法：hyperthymesia %s <%s> [--project 目录]' % ('uninstall' if remove else 'install', '|'.join(AGENTS)), file=sys.stderr); return 2
    project = argv[argv.index('--project') + 1] if '--project' in argv else None
    files = AGENTS[argv[0]](project, remove)
    print(('已移除' if remove else '已写入') + '：' + '、'.join(str(f) for f in files))
    if argv[0] == 'trae' and not remove:
        print('请在 Trae 的“设置 → Hooks”里打开钩子开关，并重启 Trae（新钩子默认不运行）。')
        print(trae_writer_check())
    if argv[0] == 'qoder' and not remove:
        print(qoder_writer_check())
    if argv[0] == 'codex' and not remove:
        print('请在 Codex 里执行 /hooks，审核并信任 hyperthymesia 的钩子（新钩子未经信任不会运行）。')
    return 0
