"""写入器的模型提供方（设计 26.5、26.6）。写入器只需要：发一段文字、拿回 JSON 文本、报告用量。

提供方由配置决定（见 config.py：环境变量 > ~/.hyperthymesia/config.toml > 自动选择本机已装的命令行）：
  codex  ：codex exec，借 ChatGPT 订阅（默认模型 gpt-5.6-luna）
  claude ：claude -p，借 Claude 订阅（默认 claude-haiku-5-5）
  codebuddy：codebuddy -p（WorkBuddy 自带），借 WorkBuddy 账号；参数与 claude 同构，支持会话续接
  qoder  ：qodercli -p，借 Qoder 账号（需另装 qodercli 并登录一次），支持系统提示与会话续接
  dsh    ：DeepSeek Harness 无头模式，借其配置的模型与 key（实验：未实测，不支持会话续接）
  openai ：任意 OpenAI 兼容接口（OpenAI、DeepSeek 等）；key 只从配置里写明的环境变量读取，强制 JSON 输出
  fake   ：测试用，按顺序返回预设回答（不调用任何模型）
所有提供方返回 Reply(sid, text, usage)；usage 统一为 input_tokens / cached_input_tokens / output_tokens。
sid 是可续接的会话编号：codex/claude 由命令行给出，openai 由本地保存的消息历史实现（接口本身无状态）。"""
import json, os, shutil, subprocess, tempfile, uuid
from collections import namedtuple
from pathlib import Path

Reply = namedtuple('Reply', 'sid text usage')
DEFAULT_MODEL = {'codex': 'gpt-5.6-luna', 'claude': 'claude-haiku-5-5', 'codebuddy': 'glm-5.3-flash'}


class ProviderError(RuntimeError):
    pass


def settings():
    from . import config
    return config.writer_settings()


def name():
    return settings()['provider']


def model():
    """配置/环境变量指定的模型优先；否则自动识别该提供方最便宜且够用的模型（缓存一周），识别不出才用默认。"""
    m = settings()['model']
    if m: return m
    if name() in ('codex', 'claude', 'codebuddy', 'qoder', 'dsh'):
        from . import models
        m = models.choose(name())
    return m or DEFAULT_MODEL.get(name(), '')


def _workdir(home):
    d = Path(home) / 'writer_work'; d.mkdir(parents=True, exist_ok=True); return d   # 空目录：命令行不会读到任何项目文件


def _codex(home, system, prompt, sid, log):
    exe = shutil.which('codex')
    if not exe: raise ProviderError('找不到 codex 命令')
    out = Path(tempfile.mkstemp(prefix='am_', suffix='.txt', dir=_workdir(home))[1])
    sysf = _workdir(home) / 'writer_rules.txt'
    if not sysf.exists() or sysf.read_text(encoding='utf-8') != system: sysf.write_text(system, encoding='utf-8')
    base = ['-m', model(), '-c', 'model_reasoning_effort="low"', '-c', 'approval_policy="never"',
            '-c', 'features.shell_tool=false', '-c', 'features.multi_agent=false', '-c', 'features.apps=false',
            '-c', 'features.code_mode.enabled=false', '-c', 'features.goals=false', '-c', 'web_search="disabled"',
            '-c', 'features.view_image=false', '-c', 'features.image_generation=false', '-c', 'features.plugins=false',
            '-c', 'model_instructions_file=' + json.dumps(str(sysf)),
            # 实测可把 codex 固定前缀从 3476 降到 2529 token：去掉环境、权限、技能说明和计划工具
            '-c', 'include_environment_context=false', '-c', 'include_permissions_instructions=false',
            '-c', 'skills.include_instructions=false', '-c', 'tools.update_plan.enabled=false',
            '--json', '--skip-git-repo-check', '--ignore-user-config', '-o', str(out)]
    cmd = [exe, 'exec'] + (['resume'] + base + [sid, '-'] if sid else base + ['-s', 'read-only', '-'])
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding='utf-8', errors='replace',
                       cwd=_workdir(home), timeout=1800)
    ev = []
    for l in r.stdout.splitlines():
        try: ev.append(json.loads(l))
        except ValueError: pass
    sid = sid or next((e['thread_id'] for e in ev if e.get('type') == 'thread.started'), None)
    done = [e for e in ev if e.get('type') == 'turn.completed']
    if r.returncode or not done or not out.exists():
        raise ProviderError('codex 调用失败：' + (r.stderr or '')[-400:])
    text = out.read_text(encoding='utf-8'); out.unlink()
    u = done[-1].get('usage', {})
    return Reply(sid, text, {'input_tokens': u.get('input_tokens', 0), 'cached_input_tokens': u.get('cached_input_tokens', 0),
                             'output_tokens': u.get('output_tokens', 0)})


def _claude(home, system, prompt, sid, log):
    exe = shutil.which('claude')
    if not exe: raise ProviderError('找不到 claude 命令')
    cmd = [exe, '-p', '--model', model(), '--output-format', 'json', '--tools', '', '--setting-sources', 'project',
           '--strict-mcp-config', '--system-prompt', system] + (['--resume', sid] if sid else [])
    env = {k: v for k, v in os.environ.items() if not k.startswith(('CLAUDECODE', 'CLAUDE_CODE_'))}   # 钩子拉起的写入器是独立会话
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding='utf-8', errors='replace',
                       cwd=_workdir(home), timeout=1800, env=env)
    try: o = json.loads(r.stdout)
    except ValueError: raise ProviderError('claude 输出无法解析：' + (r.stderr or r.stdout)[-400:])
    if r.returncode or o.get('is_error'): raise ProviderError('claude 调用失败：' + str(o.get('result'))[:400])
    u = o.get('usage', {}); cr = u.get('cache_read_input_tokens', 0)
    return Reply(o.get('session_id') or sid, o.get('result', ''),
                 {'input_tokens': u.get('input_tokens', 0) + cr + u.get('cache_creation_input_tokens', 0),
                  'cached_input_tokens': cr, 'output_tokens': u.get('output_tokens', 0), 'cost': o.get('total_cost_usd')})


def _codebuddy(home, system, prompt, sid, log):
    from .install import codebuddy_exe
    exe = codebuddy_exe()
    if not exe: raise ProviderError('找不到 codebuddy 命令行（WorkBuddy 安装包里自带一份）')
    cmd = [exe, '-p', '--output-format', 'json', '--tools', '', '--strict-mcp-config', '--system-prompt', system] + \
          (['--model', model()] if model() else []) + (['--resume', sid] if sid else [])
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=_workdir(home), timeout=1800)
    try: o = json.loads(r.stdout)
    except ValueError: raise ProviderError('codebuddy 输出无法解析：' + (r.stderr or r.stdout)[-400:])
    credit = None
    if isinstance(o, list):   # 输出为事件数组：取最后的结果，消耗累加各条消息里的 credit
        credit = sum(((x.get('providerData') or {}).get('rawUsage') or {}).get('credit') or 0 for x in o if isinstance(x, dict))
        o = next((x for x in reversed(o) if x.get('type') == 'result'), {})
    if r.returncode or o.get('is_error'): raise ProviderError('codebuddy 调用失败：' + str(o.get('result'))[:400])
    u = o.get('usage', {}); cr = u.get('cache_read_input_tokens', 0)
    return Reply(o.get('session_id') or sid, o.get('result', ''),
                 {'input_tokens': u.get('input_tokens', 0), 'cached_input_tokens': cr, 'output_tokens': u.get('output_tokens', 0), 'cost': credit})


def _openai(home, system, prompt, sid, log):
    import urllib.request
    from . import config
    s = settings(); base = (s['base_url'] or 'https://api.openai.com/v1').rstrip('/')
    key, var = config.api_key(s)
    if not key: raise ProviderError('openai 提供方读不到 key：请设置环境变量 %s（配置里的 api_key_env 指定变量名）' % var)
    if not model(): raise ProviderError('openai 提供方需要在配置里写明 model')
    sid = sid or 'api-' + uuid.uuid4().hex[:12]; hp = _workdir(home) / (sid + '.json')
    msgs = json.loads(hp.read_text(encoding='utf-8')) if hp.exists() else [{'role': 'system', 'content': system}]
    msgs.append({'role': 'user', 'content': prompt})
    req = urllib.request.Request(base + '/chat/completions', headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'},
                                 data=json.dumps({'model': model(), 'messages': msgs, 'response_format': {'type': 'json_object'}}).encode())
    try:
        with urllib.request.urlopen(req, timeout=1800) as resp: o = json.loads(resp.read())
    except Exception as exc:
        raise ProviderError('openai 接口调用失败：%s' % exc)
    text = o['choices'][0]['message']['content'] or ''; u = o.get('usage', {})
    msgs.append({'role': 'assistant', 'content': text}); hp.write_text(json.dumps(msgs, ensure_ascii=False), encoding='utf-8')
    return Reply(sid, text, {'input_tokens': u.get('prompt_tokens', 0), 'output_tokens': u.get('completion_tokens', 0),
                             'cached_input_tokens': (u.get('prompt_tokens_details') or {}).get('cached_tokens', 0)})


def _one_shot_cli(home, cmd, prompt):
    """不支持系统提示和会话续接的命令行：规则拼在请求前面，每次都是新会话。"""
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding='utf-8', errors='replace',
                       cwd=_workdir(home), timeout=1800)
    if r.returncode: raise ProviderError('%s 调用失败：%s' % (cmd[0], (r.stderr or r.stdout)[-400:]))
    return r.stdout


def qodercli_cmd():
    """qodercli 是 Node 脚本：用它旁边的 node 运行，不依赖系统默认 Node 版本（旧版本会直接报语法错误，已实测）。"""
    exe = shutil.which('qodercli')
    if not exe: return None
    node = Path(exe).resolve().parent / ('node.exe' if os.name == 'nt' else 'node')
    sib = Path(exe).parent / ('node.exe' if os.name == 'nt' else 'node')
    for n in (sib, node):
        if n.exists(): return [str(n), exe]
    return [exe]


def _qoder(home, system, prompt, sid, log):
    cmd0 = qodercli_cmd()
    if not cmd0: raise ProviderError('找不到 qodercli（npm install -g @qoder-ai/qodercli，然后 qodercli login）')
    cmd = cmd0 + ['-p', '-o', 'json', '--tools', '', '--strict-mcp-config', '--system-prompt', system] + \
          (['--model', model()] if model() else []) + (['--resume', sid] if sid else [])
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=_workdir(home), timeout=1800)
    lines = [l for l in (r.stdout or '').splitlines() if l.strip().startswith('{')]
    try: o = json.loads(lines[-1])
    except (ValueError, IndexError): raise ProviderError('qodercli 输出无法解析：' + (r.stderr or r.stdout)[-400:])
    if o.get('is_error'): raise ProviderError('qodercli 调用失败：' + str(o.get('errors') or o.get('result'))[:400])
    u = o.get('usage', {}); cr = u.get('cache_read_input_tokens', 0)
    return Reply(o.get('session_id') or sid, o.get('result', ''),
                 {'input_tokens': u.get('input_tokens', 0) + cr + u.get('cache_creation_input_tokens', 0), 'cached_input_tokens': cr,
                  'output_tokens': u.get('output_tokens', 0), 'cost': o.get('total_credits')})


def _dsh(home, system, prompt, sid, log):
    """dsh 无头模式：一次性回答后把最终回复写到 stdout。用补丁层把模型固定为 DeepSeek 官方最便宜的模型，
    并停用 settings 插件——否则用户在 dsh 里选过的默认模型（settings.yaml）会盖过补丁。key 由 dsh 自己的凭据层读取。"""
    exe = shutil.which('dsh')
    if not exe: raise ProviderError('找不到 dsh 命令')
    m = model()
    patch = _workdir(home) / 'dsh-writer.yml'
    want = ('- id: settings\n  disabled: true\n' +
            ('- id: agent-default-model\n  config:\n    provider: deepseek-official\n    model: %s\n' % json.dumps(m) if m else ''))
    if not patch.exists() or patch.read_text(encoding='utf-8') != want: patch.write_text(want, encoding='utf-8')
    text = _one_shot_cli(home, [exe, '--profile', 'headless', '--patch', str(patch), system + '\n\n' + prompt], '')
    log.append({'step': 'dsh_call', 'model': m, 'prompt_chars': len(prompt)})
    return Reply(None, text, {'input_tokens': 0, 'cached_input_tokens': 0, 'output_tokens': 0})   # 无头模式不报告用量


FAKE_REPLIES = []   # 测试用：依次弹出的回答文本；可为函数 f(prompt) -> text


def _fake(home, system, prompt, sid, log):
    if not FAKE_REPLIES: raise ProviderError('fake 提供方没有预设回答')
    r = FAKE_REPLIES.pop(0); text = r(prompt) if callable(r) else r
    log.append({'step': 'fake_call', 'prompt_chars': len(prompt)})
    return Reply(sid or 'fake-' + uuid.uuid4().hex[:6], text, {'input_tokens': len(prompt), 'cached_input_tokens': 0, 'output_tokens': len(text)})


def call(home, system, prompt, sid=None, log=None):
    fn = {'codex': _codex, 'claude': _claude, 'codebuddy': _codebuddy, 'qoder': _qoder, 'dsh': _dsh, 'openai': _openai, 'fake': _fake}.get(name())
    if not fn: raise ProviderError('没有可用的写入模型：请安装 codex/claude 等命令行，或在 ~/.hyperthymesia/config.toml 里配置' if not name() else '未知提供方：%s' % name())
    return fn(home, system, prompt, sid, log if log is not None else [])
