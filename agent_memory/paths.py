"""记忆存放位置（设计 26.7、27.3）。

~/.agent-memory/                      （Windows 为 %USERPROFILE%\\.agent-memory\\；可用 AGENT_MEMORY_HOME 覆盖）
  personal.db                         个人库：在所有项目里都成立的用户事实
  projects/<key>.db                   项目库：每个项目一个，只在该项目内可见
  projects/<key>.json                 记录这个 key 对应哪个目录（给人和 doctor 看）
  config.toml, logs/

项目 = 包含会话工作目录的 git 工作树根目录；不在 git 仓库里时就是工作目录本身。
没有工作目录的会话（纯聊天）没有项目库。"""
import hashlib, json, os, subprocess
from pathlib import Path


def home() -> Path:
    h = os.environ.get('AGENT_MEMORY_HOME')
    p = Path(h).expanduser() if h else Path.home() / '.agent-memory'
    p.mkdir(parents=True, exist_ok=True)
    return p


def project_root(cwd):
    """cwd 在 git 工作树内时返回仓库根目录，否则返回 cwd 本身；没有 cwd 时返回 None。"""
    if not cwd:
        return None
    cwd = Path(cwd).resolve()
    try:
        r = subprocess.run(['git', '-C', str(cwd), 'rev-parse', '--show-toplevel'], capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            return Path(r.stdout.strip()).resolve()
    except (OSError, subprocess.SubprocessError):
        pass   # 没装 git：工作目录就是项目
    return cwd


def project_key(root: Path) -> str:
    """稳定、可作文件名的 key：可读的文件夹名 + 完整路径的哈希（同名文件夹在不同路径下互不混淆）。"""
    name = ''.join(c if c.isalnum() or c in '-_' else '-' for c in root.name)[:40] or 'project'
    return '%s-%s' % (name, hashlib.sha1(str(root).lower().encode()).hexdigest()[:10])


def personal_db() -> Path:
    return home() / 'personal.db'


def project_db(cwd):
    """返回会话工作目录对应的（项目库路径, 项目根目录）；不在任何项目里时返回 (None, None)。"""
    root = project_root(cwd)
    if root is None:
        return None, None
    d = home() / 'projects'
    d.mkdir(exist_ok=True)
    key = project_key(root)
    meta = d / (key + '.json')
    if not meta.exists():
        meta.write_text(json.dumps({'root': str(root)}, ensure_ascii=False))
    return d / (key + '.db'), root
