"""Resolve native CLI entrypoints without passing model arguments through cmd.exe."""
import json, os, re, shutil, sys
from pathlib import Path

WINDOWS = sys.platform == 'win32'


def _windows_workbuddy_roots():
    if not WINDOWS: return []
    import winreg
    roots = []
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, r'Software\Microsoft\Windows\CurrentVersion\App Paths\WorkBuddy.exe', 0, winreg.KEY_READ | view) as key:
                    roots.append(Path(winreg.QueryValueEx(key, '')[0].strip('"')).parent)
            except OSError: pass
            try:
                with winreg.OpenKey(hive, r'Software\Microsoft\Windows\CurrentVersion\Uninstall', 0, winreg.KEY_READ | view) as key:
                    for i in range(winreg.QueryInfoKey(key)[0]):
                        try:
                            with winreg.OpenKey(key, winreg.EnumKey(key, i)) as app:
                                if 'workbuddy' not in str(winreg.QueryValueEx(app, 'DisplayName')[0]).lower(): continue
                                try: roots.append(Path(winreg.QueryValueEx(app, 'InstallLocation')[0]))
                                except OSError:
                                    icon = str(winreg.QueryValueEx(app, 'DisplayIcon')[0])
                                    roots.append(Path(icon.split('"')[1] if icon.startswith('"') else icon.split(',')[0]).parent)
                        except OSError: pass
            except OSError: pass
    return roots


def find_codebuddy():
    explicit = os.environ.get('HYPERTHYMESIA_CODEBUDDY_CLI')
    if explicit:
        p = Path(explicit).expanduser()
        if not p.is_file(): raise ValueError('HYPERTHYMESIA_CODEBUDDY_CLI points to a missing CLI entrypoint')
        command(str(p), '@tencent-ai/codebuddy-code', 'codebuddy')
        return str(p)
    candidates = []
    explicit_root = os.environ.get('WORKBUDDY_INSTALL_DIR')
    if not explicit_root:
        candidates.append(shutil.which('codebuddy'))
        # which只返回第一个；它不可用时继续搜索PATH中的其他安装。
        extensions = ['', '.exe', '.cmd', '.bat', '.ps1'] if WINDOWS else ['']
        for directory in os.get_exec_path():
            candidates.extend(str(Path(directory) / ('codebuddy' + ext)) for ext in extensions)
    if not WINDOWS and not explicit_root: candidates.append('/Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/cli/bin/codebuddy')
    roots = []
    if os.environ.get('WORKBUDDY_INSTALL_DIR'): roots.append(Path(os.environ['WORKBUDDY_INSTALL_DIR']))
    if WINDOWS:
        roots += _windows_workbuddy_roots()
        for name in ('LOCALAPPDATA', 'ProgramFiles', 'ProgramFiles(x86)'):
            if os.environ.get(name):
                base = Path(os.environ[name]); roots += [base / 'WorkBuddy', base / 'Programs' / 'WorkBuddy']
    for root in roots:
        for name in ('resources/app.asar.unpacked/cli/bin/codebuddy', 'resources/app.asar.unpacked/cli/bin/codebuddy.cmd', 'resources/app.asar.unpacked/cli/dist/codebuddy-lite-wb.mjs'):
            candidates.append(str(root / name))
    errors = []; checked = set()
    for p in candidates:
        if not p or str(p) in checked or not Path(p).is_file(): continue
        checked.add(str(p))
        try:
            command(str(p), '@tencent-ai/codebuddy-code', 'codebuddy')
            return str(p)
        except (OSError, ValueError) as exc:
            # 自动探测的坏包装不应挡住后面的真实入口；显式指定的入口仍准确报错。
            errors.append(str(exc))
    if errors: raise ValueError('No usable codebuddy CLI entrypoint: ' + '; '.join(errors))
    return None


def _script_from_shim(path, package, command):
    # npm's package.json owns the executable mapping; do not guess a versioned bundle layout.
    for prefix in (path.parent, path.parent.parent):
        meta = prefix / 'node_modules' / package / 'package.json'
        if not meta.is_file(): continue
        data = json.loads(meta.read_text(encoding='utf-8-sig'))
        entry = data.get('bin'); entry = entry.get(command) if isinstance(entry, dict) else entry
        if entry and (meta.parent / entry).is_file(): return (meta.parent / entry).resolve()
    # Also handle wrappers pointing at desktop bundles outside npm's layout.
    text = path.read_text(encoding='utf-8-sig', errors='replace')
    for match in re.finditer(r'"([^"\r\n]+)"', text):
        value = match.group(1).replace('%~dp0', str(path.parent) + os.sep).replace('%dp0%', str(path.parent) + os.sep)
        target = Path(os.path.expandvars(value))
        if target.is_file() and target.suffix.lower() not in ('.exe', '.cmd', '.bat', '.ps1'):
            if target.suffix.lower() in ('.js', '.mjs', '.cjs') or b'node' in target.read_bytes()[:120]: return target.resolve()
    raise ValueError('Cannot resolve JavaScript entrypoint from ' + str(path) + '; configure the actual CLI script, not a .cmd wrapper')


def command(executable, package='', name=''):
    if not executable: return None
    path = Path(executable)
    shell_shim = False
    if WINDOWS and not path.suffix and path.is_file():
        with path.open('rb') as stream: first = stream.read(256).split(b'\n', 1)[0].lower()
        shell_shim = (first.startswith(b'#!') and b'node' not in first) or first.startswith((b'@echo', b'node ', b'@node '))
    if path.suffix.lower() in ('.cmd', '.bat', '.ps1') or shell_shim:
        path = _script_from_shim(path, package, name)
    else: path = path.resolve()
    if path.suffix.lower() == '.exe': return [str(path)]
    nodes = [Path(executable).parent / ('node.exe' if WINDOWS else 'node'), path.parent / ('node.exe' if WINDOWS else 'node')]
    found = shutil.which('node')
    if found: nodes.append(Path(found))
    node = next((p for p in nodes if p.is_file()), None)
    if node: return [str(node), str(path)]
    if WINDOWS: raise ValueError('Node.js is required to launch the bundled JavaScript CLI; install Node.js LTS or add node.exe to PATH')
    return [str(path)]  # Unix executable/shebang remains supported.


def environment(agent, cmd, inherited=None):
    env = dict(os.environ if inherited is None else inherited)
    if agent == 'qoder':
        # These select SDK transport/worker mode, not the user's CLI login credentials.
        for key in ('QODER_AGENT_SDK_ENTRYPOINT', 'QODER_AGENT_SDK_DAEMON', 'QODER_AGENT_SDK_VERSION'):
            env.pop(key, None)
    if agent == 'codebuddy':
        for value in cmd:
            path = Path(value)
            dist = path.parent if path.parent.name == 'dist' else path.parent.parent / 'dist'
            if (dist / 'codebuddy-lite-wb.mjs').is_file():
                env['CODEBUDDY_FORCE_LITE_WB_BUNDLE'] = '1'
                break
    return env
