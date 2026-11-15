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


def trae_writer_check():
    """Trae 暂不支持用自身额度写入（TRAE CLI 个人账号无模型可用）：只检查用户是否在配置里填了 API key。"""
    from . import config
    if (config.load().get('writer') or {}).get('provider'):
        return '已在配置里指定写入用的模型：记忆整理将使用该配置。'
    return ('提示：Trae 暂不支持用 Trae 自己的额度整理记忆。记忆的读取正常可用；要启用整理，'
            '请在 ~/.hyperthymesia/config.toml 的 [writer] 里配置自己的 API key（见 README“用 API key 的用户”）。')



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


DSH_HOOKS_PKG = '@deepseek-ai/dsh-hooks-claude-code'
DSH_PKGS = [DSH_HOOKS_PKG, '@deepseek-ai/dsh-hook-protocol']   # 桥接插件依赖 hook-protocol，dsh 本体没带


def dsh_home():
    return Path(os.environ.get('DSH_HOME') or Path(os.environ.get('HOME') or Path.home()) / '.dsh')


def _dsh_profiles():
    """要接入的 dsh 交互 profile（web、tui 等）；headless 是写入器自己用的无头模式，不装钩子，避免写入时又触发钩子。"""
    d = dsh_home() / 'profiles'
    return [p for p in sorted(d.iterdir()) if p.is_dir() and p.name not in ('node_modules', 'headless') and (p / 'package.json').exists()] if d.exists() else []


def _yaml_q(v): return json.dumps(str(v), ensure_ascii=False)   # JSON 字符串即合法的 YAML 双引号字符串


def dsh(project=None, remove=False):
    """DeepSeek Harness：钩子由官方桥接插件 dsh-hooks-claude-code 运行（Claude Code 格式的 hooks.json，放在本框架目录）；
    MCP 用 dsh 自带的 dsh-mcp-client。两者以带标记的一段 insert 追加到每个交互 profile 的 cordis.patch.yml（用户层补丁）。
    不写 $DSH_HOME/cordis.patch.yml：那一层对 headless 也生效，写入器会递归触发钩子。"""
    from . import paths
    hp = paths.home() / 'dsh-hooks.json'
    if not remove:
        hooks = {ev: [{'hooks': [{'type': 'command', 'command': _cmd('hook', name, '--agent', 'dsh'), 'timeout': 60}]}]
                 for ev, name in CODEX_EVENTS.items()}   # 桥接只支持 SessionStart / UserPromptSubmit / Stop 等，没有压缩前与会话结束
        _save(hp, {'hooks': hooks})
    elif hp.exists(): hp.unlink()
    profiles = _dsh_profiles()
    if not remove and not profiles:
        raise SystemExit('没有找到 dsh 的 profile（%s/profiles）：请先运行一次 dsh web' % dsh_home())
    c = self_cmd(); out = [hp]
    for prof in profiles:
        pp = prof / 'cordis.patch.yml'
        text = pp.read_text(encoding='utf-8') if pp.exists() else ''
        a, b = text.find(MARK_BEGIN), text.find(MARK_END)
        if a >= 0 and b > a: text = text[:a].rstrip('\n') + '\n' + text[b + len(MARK_END):].lstrip('\n')
        body = [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith('#')]
        if not remove:
            missing = [k for k in DSH_PKGS if not (prof / 'node_modules' / k).exists()]
            if missing:
                print('正在为 dsh 的 %s profile 安装官方钩子桥接插件 ……' % prof.name)
                env = dict(os.environ)
                if not shutil.which('pnpm') and shutil.which('npx'):   # dsh plugin 需要 pnpm；没装时用 npx 临时调用官方 pnpm，不做全局安装
                    shim = paths.home() / 'pnpm-shim'; shim.mkdir(parents=True, exist_ok=True)
                    if os.name == 'nt': (shim / 'pnpm.cmd').write_text('@npx -y pnpm@10 %*\r\n', encoding='utf-8')
                    else: (shim / 'pnpm').write_text('#!/bin/sh\nexec npx -y pnpm@10 "$@"\n', encoding='utf-8'); (shim / 'pnpm').chmod(0o755)
                    env['PATH'] = str(shim) + os.pathsep + env.get('PATH', '')
                for k in missing: _run_quiet([shutil.which('dsh') or 'dsh', 'plugin', '--profile', prof.name, 'add', k], env=env)
                if any(not (prof / 'node_modules' / k).exists() for k in DSH_PKGS):
                    raise SystemExit('dsh 钩子桥接插件安装失败：请先安装 pnpm（npm install -g pnpm）后重试')
            if [l.strip() for l in body] == ['[]']:   # 空补丁写成流式 [] 时，后面不能再接块列表
                text = '\n'.join(l for l in text.splitlines() if l.strip() != '[]')
            # 钩子插件放进一个组，组内单独挂一个本机 shell（isolate）：dsh 默认 shell 是沙箱，只许写项目目录，
            # 钩子要写 ~/.hyperthymesia；隔离后只影响本组，agent 自己执行的命令仍在沙箱里（已实测）
            block = '\n'.join([MARK_BEGIN, '- insert:',
                               '    - id: hyperthymesia', "      name: '@deepseek-ai/cordis-plugin-group'", '      group: true',
                               '      isolate:', '        shell: true', '      config:',
                               '        - id: shell', "          name: '@deepseek-ai/dsh-bash-local'",
                               '        - id: hooks', "          name: '%s'" % DSH_HOOKS_PKG,
                               '          config:', '            configPath: ' + _yaml_q(hp),
                               '    - id: hyperthymesia-mcp', "      name: '@deepseek-ai/dsh-mcp-client'",
                               '      config:', '        serverName: hyperthymesia', '        transport: stdio',
                               '        command: ' + _yaml_q(c[0]),
                               '        args: [%s]' % ', '.join(_yaml_q(x) for x in c[1:] + ['serve']), MARK_END])
            text = text.rstrip('\n') + '\n\n' + block + '\n'
        elif not [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith('#')]:
            text = text.rstrip('\n') + '\n[]\n'
        pp.parent.mkdir(parents=True, exist_ok=True); _backup(pp); pp.write_text(text, encoding='utf-8'); out.append(pp)
    return out


def dsh_writer_check():
    """dsh 写入用 DeepSeek 官方最便宜的模型、用户在 dsh 里存的 DeepSeek key（由 dsh 自己读取，本框架不碰 key）。"""
    if not shutil.which('dsh'): return '找不到 dsh 命令：记忆可以读取，但无法整理。'
    return '写入将借用 dsh 的无头模式，用 DeepSeek 官方最便宜的模型和你在 dsh 里配置的 DeepSeek key。'


AGENTS = {'dsh': dsh, 'trae': trae, 'claude': claude, 'codex': codex, 'workbuddy': codebuddy, 'codebuddy': codebuddy, 'qoder': qoder}   # workbuddy 与 codebuddy 同一套（WorkBuddy 底层是 CodeBuddy）


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
    if argv[0] == 'dsh' and not remove:
        print(dsh_writer_check())
    if argv[0] == 'qoder' and not remove:
        print(qoder_writer_check())
    if argv[0] == 'codex' and not remove:
        print('请在 Codex 里执行 /hooks，审核并信任 hyperthymesia 的钩子（新钩子未经信任不会运行）。')
    return 0
