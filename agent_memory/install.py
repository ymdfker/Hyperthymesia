"""agent-memory install/uninstall <agent>：给 agent 写入（或移除）MCP 服务与钩子配置。

原则：只增删本框架自己的条目，用户原有配置原样保留；改动前把原文件备份为 *.hyperthymesia.bak。
- claude：用户级 ~/.claude/settings.json 加钩子，~/.claude.json 的 mcpServers 加服务（--project 目录 时改为该项目的
  .claude/settings.local.json 和 .mcp.json）。
- codex：~/.codex/config.toml 末尾追加一段带标记的配置（--project 时为该项目的 .codex/config.toml）。
  Codex 的新钩子必须由用户在 Codex 里执行 /hooks 审核信任后才会运行，安装后会提示。"""
import json, os, shutil, sys
from pathlib import Path

from .hooks import self_cmd

NAME = 'hyperthymesia'
MARK_BEGIN = '# >>> hyperthymesia（由 agent-memory install 生成，uninstall 会删除这一段）'
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


def _is_ours(h): return NAME in json.dumps(h) or 'agent_memory' in json.dumps(h) or 'agent-memory' in json.dumps(h)


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


AGENTS = {'claude': claude, 'codex': codex, 'codebuddy': codebuddy}


def run(argv, remove=False):
    """agent-memory install|uninstall <claude|codex> [--project 目录]"""
    if not argv or argv[0] not in AGENTS:
        print('用法：agent-memory %s <%s> [--project 目录]' % ('uninstall' if remove else 'install', '|'.join(AGENTS)), file=sys.stderr); return 2
    project = argv[argv.index('--project') + 1] if '--project' in argv else None
    files = AGENTS[argv[0]](project, remove)
    print(('已移除' if remove else '已写入') + '：' + '、'.join(str(f) for f in files))
    if argv[0] == 'codex' and not remove:
        print('请在 Codex 里执行 /hooks，审核并信任 hyperthymesia 的钩子（新钩子未经信任不会运行）。')
    return 0
