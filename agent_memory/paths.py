"""Where memory lives (design 26.7, 27.3).

~/.agent-memory/                      (Windows: %USERPROFILE%\\.agent-memory\\; override with AGENT_MEMORY_HOME)
  personal.db                         facts about the user that hold in every project
  projects/<key>.db                   one store per project, visible only inside that project
  projects/<key>.json                 which directory a project key stands for (for humans and `doctor`)
  config.toml, logs/

A project is the git work-tree root that contains the session's working directory; outside any git repository it is
the working directory itself. A session with no working directory (plain chat) has no project store."""
import hashlib, json, os, subprocess
from pathlib import Path


def home() -> Path:
    h = os.environ.get('AGENT_MEMORY_HOME')
    p = Path(h).expanduser() if h else Path.home() / '.agent-memory'
    p.mkdir(parents=True, exist_ok=True)
    return p


def project_root(cwd):
    """git top level of cwd if it is inside a work tree, else cwd itself; None when there is no cwd."""
    if not cwd:
        return None
    cwd = Path(cwd).resolve()
    try:
        r = subprocess.run(['git', '-C', str(cwd), 'rev-parse', '--show-toplevel'], capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            return Path(r.stdout.strip()).resolve()
    except (OSError, subprocess.SubprocessError):
        pass   # no git installed: the working directory is the project
    return cwd


def project_key(root: Path) -> str:
    """stable, filesystem-safe key: readable folder name + hash of the full path (two folders with one name differ)."""
    name = ''.join(c if c.isalnum() or c in '-_' else '-' for c in root.name)[:40] or 'project'
    return '%s-%s' % (name, hashlib.sha1(str(root).lower().encode()).hexdigest()[:10])


def personal_db() -> Path:
    return home() / 'personal.db'


def project_db(cwd):
    """(db path, project root) for the session's working directory, or (None, None) outside any project."""
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
