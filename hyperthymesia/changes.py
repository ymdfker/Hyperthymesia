"""每轮工作区改动（设计 23.58–23.62、26.3 A1），与宿主无关。

轮次开始拍快照，轮次结束再拍快照，两者对比 -> 本轮给写入器的改动块。
- 装了 git：用影子仓库（独立 git-dir 放在 <home>/shadow，工作树 = agent 的 cwd）。
  不碰用户自己的仓库、暂存区和历史；.gitignore 照样生效；非 git 目录也能用。
- 没装 git：纯文件快照（小文本文件全文）存在 <home>/snapshots，用 difflib 对比。
两种方式都排除依赖/构建目录、二进制、日志、数据库和凭据文件；改动块还会再过一遍 redact()。"""
import difflib, fnmatch, hashlib, json, os, re, shutil, subprocess, time
from pathlib import Path
from .redact import redact

EXCLUDE = ['.git/', 'node_modules/', '.venv/', 'venv/', '__pycache__/', '*.pyc', '.DS_Store', 'dist/', 'build/', '.next/', 'target/',
           '.env', '.env.*', '!.env.example', '!.env.sample', '!.env.template', '*.pem', '*.key', '*.p12', '*.pfx', '*.keystore', '*.jks',
           'id_rsa*', 'id_dsa*', 'id_ecdsa*', 'id_ed25519*', '.npmrc', '.pypirc', '.netrc', '.pgpass', '.git-credentials', 'credentials',
           'credentials.*', 'secrets.*', '*.secret', 'kubeconfig', '.aws/', '.ssh/', '.gnupg/',
           '*.sqlite', '*.sqlite3', '*.db', '*.db-wal', '*.db-shm', '*.log', '*.zip', '*.tar*', '*.gz', '*.png', '*.jpg', '*.jpeg', '*.gif',
           '*.pdf', '*.mp4', '*.bin', '*.exe', '*.dll', '*.so', '*.dylib']
MAX_FILE = 512 * 1024
CAP = int(os.environ.get('HYPERTHYMESIA_CHANGE_CAP', '4000'))
PRIORITY = re.compile(r'(config|settings|\.toml|\.ini|\.ya?ml|\.json|\.env\.example|docs/|README|CONTRIBUTING|\.md$)', re.I)


def has_git():
    return shutil.which('git') is not None


def _key(cwd): return hashlib.sha1(str(Path(cwd).resolve()).encode()).hexdigest()[:16]


# ---------- git 影子仓库
def _shadow(home, cwd):
    d = Path(home) / 'shadow' / _key(cwd)
    if not (d / 'HEAD').exists():
        d.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', 'init', '-q', '--bare', str(d)], check=True, capture_output=True)
        (d / 'info').mkdir(exist_ok=True)
    ex = d / 'info' / 'exclude'; lines = list(EXCLUDE)
    try: lines.append('/' + Path(home).resolve().relative_to(Path(cwd).resolve()).as_posix() + '/')   # 记忆目录在工作区内时排除它
    except ValueError: pass
    if not ex.exists() or ex.read_text(encoding='utf-8') != '\n'.join(lines) + '\n': ex.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return d


def _git(gd, cwd, *a, inp=None):
    env = dict(os.environ, GIT_DIR=str(gd), GIT_WORK_TREE=str(cwd), GIT_INDEX_FILE=str(Path(gd) / 'index'))
    return subprocess.run(['git'] + list(a), cwd=str(cwd), env=env, capture_output=True, text=True, input=inp, timeout=120,
                          encoding='utf-8', errors='replace')


def _git_snapshot(home, cwd):
    gd = _shadow(home, cwd)
    _git(gd, cwd, 'add', '-A', '--ignore-errors', '.')
    staged = _git(gd, cwd, 'ls-files', '-s').stdout.splitlines()
    if staged:
        sizes = _git(gd, cwd, 'cat-file', '--batch-check', inp='\n'.join(l.split()[1] for l in staged)).stdout.splitlines()
        drop = [l.split('\t', 1)[1] for l, sz in zip(staged, sizes) if len(sz.split()) == 3 and int(sz.split()[2]) > MAX_FILE]
        if drop: _git(gd, cwd, 'rm', '--cached', '-q', '--', *drop)
    return 'git:' + _git(gd, cwd, 'write-tree').stdout.strip()


def _git_diff(home, cwd, a, b):
    gd = _shadow(home, cwd); a, b = a[4:], b[4:]
    if a == b: return '', ''
    diff = _git(gd, cwd, 'diff-tree', '-p', '--unified=0', '--no-color', '--no-renames', a, b).stdout
    return diff, _git(gd, cwd, 'diff-tree', '--numstat', '--no-renames', a, b).stdout


# ---------- 纯文件快照（无 git）
def _excluded(rel, is_dir):
    name = rel.rsplit('/', 1)[-1]; hit = False
    for pat in EXCLUDE:
        neg = pat.startswith('!'); p = pat[1:] if neg else pat
        if p.endswith('/'):
            m = is_dir and fnmatch.fnmatch(name, p[:-1])
        else:
            m = fnmatch.fnmatch(name, p)
        if m: hit = not neg
    return hit


def _file_snapshot(home, cwd):
    cwd = Path(cwd).resolve(); files = {}
    homep = Path(home).resolve()
    for root, dirs, names in os.walk(cwd):
        r = Path(root)
        dirs[:] = [d for d in dirs if not _excluded(d, True) and (r / d).resolve() != homep]
        for n in names:
            if _excluded(n, False): continue
            p = r / n
            try:
                st = p.stat()
                if st.st_size > MAX_FILE: continue
                b = p.read_bytes()
            except OSError: continue
            if b'\0' in b[:4096]: continue   # 二进制文件
            files[p.relative_to(cwd).as_posix()] = b.decode('utf-8', 'replace')
    sid = hashlib.sha1(json.dumps(files, sort_keys=True).encode()).hexdigest()[:16]
    d = Path(home) / 'snapshots' / _key(cwd); d.mkdir(parents=True, exist_ok=True)
    (d / (sid + '.json')).write_text(json.dumps(files, ensure_ascii=False), encoding='utf-8')
    return 'file:' + sid


def _file_diff(home, cwd, a, b):
    if a == b: return '', ''
    d = Path(home) / 'snapshots' / _key(cwd)
    A = json.loads((d / (a[5:] + '.json')).read_text(encoding='utf-8')); B = json.loads((d / (b[5:] + '.json')).read_text(encoding='utf-8'))
    out = []; stat = []
    for path in sorted(set(A) | set(B)):
        x, y = A.get(path, ''), B.get(path, '')
        if x == y: continue
        lines = [l for l in difflib.unified_diff(x.splitlines(), y.splitlines(), lineterm='', n=0)
                 if l[:1] in '+-' and not l.startswith(('+++', '---'))]
        out.append('diff --git a/%s b/%s\n%s' % (path, path, '\n'.join(lines)))
        stat.append('%d\t%d\t%s' % (sum(l[0] == '+' for l in lines), sum(l[0] == '-' for l in lines), path))
    return '\n'.join(out), '\n'.join(stat)


MAX_TREE_FILES = int(os.environ.get('HYPERTHYMESIA_MAX_TREE_FILES', '3000'))


def _too_big(cwd):
    """不是 git 仓库的工作目录（如主目录、装着很多仓库的大文件夹）可能有海量文件：每轮快照会把钩子拖慢几分钟（dsh 网页实测）。
    数到上限就停，超过则不记录代码改动（对话照常记录）。git 仓库本身有 .gitignore 约束，不限制。"""
    if (Path(cwd) / '.git').exists(): return False
    n = 0
    for _, dirs, files in os.walk(cwd):
        dirs[:] = [d for d in dirs if d not in ('.git', 'node_modules', '.venv', '__pycache__')]
        n += len(files)
        if n > MAX_TREE_FILES: return True
    return False


def snapshot(home, cwd):
    if _too_big(cwd): return ''
    from .writecmd import Lock
    with Lock('snapshot:' + _key(cwd), home=home, blocking=True) as lock:
        if not lock.ok: raise OSError('代码快照正在被其他进程使用')
        return _git_snapshot(home, cwd) if has_git() else _file_snapshot(home, cwd)


def diff(home, cwd, a, b):
    if a.startswith('git:') and b.startswith('git:'): return _git_diff(home, cwd, a, b)
    if a.startswith('file:') and b.startswith('file:'): return _file_diff(home, cwd, a, b)
    return '', ''   # 两次快照之间 git 装上或被卸载：跳过本轮，不做猜测


# ---------- 给写入器的改动块
def _files(diff_text):
    out = []; cur = None
    for l in diff_text.splitlines():
        if l.startswith('diff --git '): cur = [l.split(' b/', 1)[-1], []]; out.append(cur)
        elif cur and l[:1] in '+-' and not l.startswith(('+++', '---')): cur[1].append(l)
    return out


def change_block(diff_text, numstat=''):
    """按文件列出变更行，配置/文档优先；超出 CAP 的文件只列名称和增删行数，绝不把单个文件截成半截。"""
    fs = [f for f in _files(diff_text) if f[1]]
    if not fs: return ''
    fs.sort(key=lambda f: (0 if PRIORITY.search(f[0]) else 1, len('\n'.join(f[1]))))
    body = []; size = 0; rest = []
    for path, lines in fs:
        t = '[%s]\n%s' % (path, '\n'.join(lines))
        if size + len(t) <= CAP or not body: body.append(t); size += len(t)
        else: rest.append(path)
    if rest:
        ns = {l.split('\t')[2]: l.split('\t')[:2] for l in numstat.splitlines() if l.count('\t') == 2}
        body.append('（以下文件改动较大，未列出变更行：' + '；'.join('%s +%s/-%s' % (p, *ns.get(p, ['?', '?'])) for p in rest) + '）')
    body = [redact(b)[0] for b in body]
    return '\n\n【本轮工作区改动】（程序记录的代码与文件改动；“+”为新增行，“-”为删除行）\n' + '\n\n'.join(body)
