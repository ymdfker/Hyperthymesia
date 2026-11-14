"""用户配置 ~/.agent-memory/config.toml（设计 28.3）。示例：

    [writer]
    provider = "openai"                     # codex | claude | qoder | dsh | openai；不写则自动选择
    model = "deepseek-chat"
    base_url = "https://api.deepseek.com/v1"
    api_key_env = "DEEPSEEK_API_KEY"        # 只写环境变量名：本框架运行时从环境读取，不保存、不复制 key

优先级：环境变量（AGENT_MEMORY_PROVIDER / _MODEL / _BASE_URL / _API_KEY_ENV）> 配置文件 > 自动选择。
自动选择只会挑本机已安装的 agent 命令行（借用该 agent 自己的登录与额度），不会自动动用任何 API key：
使用付费 API 必须由用户在配置里明确指定。"""
import os, re, shutil
from . import paths

AUTO_ORDER = ['codex', 'claude', 'qoder', 'dsh']   # 自动选择时依次检查的命令行
CLI_EXE = {'codex': 'codex', 'claude': 'claude', 'qoder': 'qoder', 'dsh': 'dsh'}


def _parse_toml(text):
    """只支持本框架需要的子集：[节]、key = "字符串" / 数字 / true|false、# 注释。Python 3.11+ 用标准库 tomllib。"""
    try:
        import tomllib
        return tomllib.loads(text)
    except ImportError:
        pass
    out = {}; cur = out
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith('#'): continue
        m = re.fullmatch(r'\[([A-Za-z0-9_.-]+)\]', line)
        if m: cur = out.setdefault(m.group(1), {}); continue
        m = re.fullmatch(r'([A-Za-z0-9_-]+)\s*=\s*(.+?)\s*(#.*)?', line)
        if not m: continue
        v = m.group(2)
        if v.startswith('"') and v.endswith('"'): v = v[1:-1].replace('\\"', '"').replace('\\\\', '\\')
        elif v in ('true', 'false'): v = v == 'true'
        else:
            try: v = int(v)
            except ValueError:
                try: v = float(v)
                except ValueError: pass
        cur[m.group(1)] = v
    return out


def load():
    p = paths.home() / 'config.toml'
    try: return _parse_toml(p.read_text(encoding='utf-8')) if p.exists() else {}
    except Exception as exc: raise SystemExit('无法解析 %s：%s' % (p, exc))


def writer_settings():
    """返回写入器设置：{provider, model, base_url, api_key_env, source}；source 说明 provider 从哪里来。"""
    w = load().get('writer', {}) or {}
    s = {'provider': os.environ.get('AGENT_MEMORY_PROVIDER') or w.get('provider'),
         'model': os.environ.get('AGENT_MEMORY_MODEL') or w.get('model') or '',
         'base_url': os.environ.get('AGENT_MEMORY_BASE_URL') or w.get('base_url') or '',
         'api_key_env': os.environ.get('AGENT_MEMORY_API_KEY_ENV') or w.get('api_key_env') or ''}
    if s['provider']:
        s['source'] = '环境变量' if os.environ.get('AGENT_MEMORY_PROVIDER') else '配置文件'
    else:
        s['provider'] = next((p for p in AUTO_ORDER if shutil.which(CLI_EXE[p])), '')
        s['source'] = '自动选择（本机已安装的命令行）' if s['provider'] else '无可用提供方'
    return s


def api_key(s):
    """按配置的环境变量名取 key；没有配置变量名时依次尝试 AGENT_MEMORY_API_KEY、OPENAI_API_KEY。只在内存里使用。"""
    for name in ([s['api_key_env']] if s.get('api_key_env') else []) + ['AGENT_MEMORY_API_KEY', 'OPENAI_API_KEY']:
        if os.environ.get(name): return os.environ[name], name
    return None, s.get('api_key_env') or 'AGENT_MEMORY_API_KEY'
