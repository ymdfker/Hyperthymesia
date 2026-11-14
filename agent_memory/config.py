"""用户配置 ~/.agent-memory/config.toml（设计 28.3）。示例：

    [writer]
    provider = "openai"                     # codex | claude | qoder | dsh | openai；不写则自动选择
    model = "deepseek-chat"
    base_url = "https://api.deepseek.com/v1"
    api_key_env = "DEEPSEEK_API_KEY"        # 只写环境变量名：本框架运行时从环境读取，不保存、不复制 key

优先级：环境变量（AGENT_MEMORY_PROVIDER / _MODEL / _BASE_URL / _API_KEY_ENV）> 配置文件 > 宿主 agent > 自动选择。
规则（用户确认）：订阅用户的写入用宿主 agent 自己的便宜模型和额度（WorkBuddy 用 WorkBuddy 的模型，Claude Code 用 Haiku，
Codex 用 luna），不借别家 agent；API key 用户用该 key 支持的便宜模型（在配置里写明 model）。
宿主 agent 由钩子告知（写入进程的 AGENT_MEMORY_HOST_AGENT）。自动选择只在不知道宿主时使用，只挑本机已装的命令行，
不会自动动用任何 API key：使用付费 API 必须由用户在配置里明确指定。"""
import os, re, shutil
from . import paths

AUTO_ORDER = ['codex', 'claude', 'codebuddy', 'qoder', 'dsh']   # 不知道宿主时，自动选择依次检查的命令行
# 各宿主 agent 默认用于写入的便宜模型（可在配置 [writer] model 覆盖）
CHEAP_MODEL = {'codex': 'gpt-5.6-luna', 'claude': 'claude-haiku-5-5', 'codebuddy': 'glm-5.3-flash', 'qoder': 'lite'}   # qoder 的 lite 档为文档所列的低价档，未实测
CLI_EXE = {'codex': 'codex', 'claude': 'claude', 'codebuddy': 'codebuddy', 'qoder': 'qoder', 'dsh': 'dsh'}


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
    host = os.environ.get('AGENT_MEMORY_HOST_AGENT', '')
    if s['provider']:
        s['source'] = '环境变量' if os.environ.get('AGENT_MEMORY_PROVIDER') else '配置文件'
    elif host in CLI_EXE:
        s['provider'] = host; s['source'] = '宿主 agent（用它自己的便宜模型和额度）'
    else:
        from .install import codebuddy_exe
        found = lambda p: codebuddy_exe() if p == 'codebuddy' else shutil.which(CLI_EXE[p])   # codebuddy 可能只在 WorkBuddy 安装包里
        s['provider'] = next((p for p in AUTO_ORDER if found(p)), '')
        s['source'] = '自动选择（本机已安装的命令行）' if s['provider'] else '无可用提供方'
    if not s['model']: s['model'] = CHEAP_MODEL.get(s['provider'], '')
    return s


def api_key(s):
    """按配置的环境变量名取 key；没有配置变量名时依次尝试 AGENT_MEMORY_API_KEY、OPENAI_API_KEY。只在内存里使用。"""
    for name in ([s['api_key_env']] if s.get('api_key_env') else []) + ['AGENT_MEMORY_API_KEY', 'OPENAI_API_KEY']:
        if os.environ.get(name): return os.environ[name], name
    return None, s.get('api_key_env') or 'AGENT_MEMORY_API_KEY'
