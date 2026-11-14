"""写入器的模型提供方（设计 26.5、26.6）。写入器只需要：发一段文字、拿回 JSON 文本、报告用量。

AGENT_MEMORY_PROVIDER 选择提供方：
  codex  ：codex exec，借 ChatGPT 订阅（默认模型 gpt-5.6-luna）
  claude ：claude -p，借 Claude 订阅（默认 claude-haiku-5-5）
  openai ：任意 OpenAI 兼容 HTTP 接口，key 从 AGENT_MEMORY_API_KEY 或 OPENAI_API_KEY 读取，强制 JSON 输出
  fake   ：测试用，按顺序返回预设回答（不调用任何模型）
所有提供方返回 Reply(sid, text, usage)；usage 统一为 input_tokens / cached_input_tokens / output_tokens。
sid 是可续接的会话编号：codex/claude 由命令行给出，openai 由本地保存的消息历史实现（接口本身无状态）。"""
import json, os, shutil, subprocess, tempfile, uuid
from collections import namedtuple
from pathlib import Path

Reply = namedtuple('Reply', 'sid text usage')
DEFAULT_MODEL = {'codex': 'gpt-5.6-luna', 'claude': 'claude-haiku-5-5'}


class ProviderError(RuntimeError):
    pass


def name():
    return os.environ.get('AGENT_MEMORY_PROVIDER', 'codex')


def model():
    return os.environ.get('AGENT_MEMORY_MODEL') or DEFAULT_MODEL.get(name(), '')


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
                  'cached_input_tokens': cr, 'output_tokens': u.get('output_tokens', 0)})


def _openai(home, system, prompt, sid, log):
    import urllib.request
    base = (os.environ.get('AGENT_MEMORY_BASE_URL') or 'https://api.openai.com/v1').rstrip('/')
    key = os.environ.get('AGENT_MEMORY_API_KEY') or os.environ.get('OPENAI_API_KEY')
    if not key or not model(): raise ProviderError('openai 提供方需要 AGENT_MEMORY_MODEL 和 AGENT_MEMORY_API_KEY（或 OPENAI_API_KEY）')
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


FAKE_REPLIES = []   # 测试用：依次弹出的回答文本；可为函数 f(prompt) -> text


def _fake(home, system, prompt, sid, log):
    if not FAKE_REPLIES: raise ProviderError('fake 提供方没有预设回答')
    r = FAKE_REPLIES.pop(0); text = r(prompt) if callable(r) else r
    log.append({'step': 'fake_call', 'prompt_chars': len(prompt)})
    return Reply(sid or 'fake-' + uuid.uuid4().hex[:6], text, {'input_tokens': len(prompt), 'cached_input_tokens': 0, 'output_tokens': len(text)})


def call(home, system, prompt, sid=None, log=None):
    fn = {'codex': _codex, 'claude': _claude, 'openai': _openai, 'fake': _fake}.get(name())
    if not fn: raise ProviderError('未知提供方：%s' % name())
    return fn(home, system, prompt, sid, log if log is not None else [])
