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
import json, os, shutil, subprocess, tempfile, time, uuid
from collections import namedtuple
from pathlib import Path

from .execution import internal_env

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
    """显式选择优先且不跑准入；自动模式复用验收并筛选，不通过时保留积压，不偷换提供方。"""
    m = settings()['model']
    if m: return m
    if name() in ('codex', 'claude', 'codebuddy', 'qoder', 'dsh'):
        from . import models
        m = models.choose(name())
    return m or DEFAULT_MODEL.get(name(), '')


def _run_cli(cmd, agent=None, **kwargs):
    """整理、补漏、冲突检查和模型试探统一走内部调用边界。"""
    from . import launch
    kwargs['env'] = internal_env(launch.environment(agent, cmd, kwargs.get('env')))
    return subprocess.run(cmd, **kwargs)


class cli_slot:
    """同一宿主CLI跨进程串行：多个项目的写入器同时调用时，CLI会在同一本地端口监听而冲突（EADDRINUSE）。
    非阻塞轮询拿锁（Windows 的阻塞锁只等约10秒），最多等30分钟；超时报错，积压保留。"""
    def __init__(self, home, agent, wait=1800):
        self.home, self.agent, self.wait, self.lock = home, agent, wait, None
    def __enter__(self):
        from .writecmd import Lock
        end = time.time() + self.wait
        while True:
            lk = Lock('cli:' + self.agent, home=self.home).__enter__()
            if lk.ok: self.lock = lk; return self
            if time.time() > end: raise ProviderError('%s CLI 一直被另一个写入进程占用（pid=%s），本批未调用，积压保留。' % (self.agent, lk.holder))
            time.sleep(2)
    def __exit__(self, *args):
        if self.lock: self.lock.__exit__(*args)


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
    r = _run_cli(cmd, input=prompt, capture_output=True, text=True, encoding='utf-8', errors='replace',
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
    r = _run_cli(cmd, input=prompt, capture_output=True, text=True, encoding='utf-8', errors='replace',
                       cwd=_workdir(home), timeout=1800, env=env)
    try: o = json.loads(r.stdout)
    except ValueError: raise ProviderError('claude 输出无法解析：' + (r.stderr or r.stdout)[-400:])
    if r.returncode or o.get('is_error'): raise ProviderError('claude 调用失败：' + str(o.get('result'))[:400])
    u = o.get('usage', {}); cr = u.get('cache_read_input_tokens', 0)
    return Reply(o.get('session_id') or sid, o.get('result', ''),
                 {'input_tokens': u.get('input_tokens', 0) + cr + u.get('cache_creation_input_tokens', 0),
                  'cached_input_tokens': cr, 'output_tokens': u.get('output_tokens', 0), 'cost': o.get('total_cost_usd')})


def codebuddy_cmd():
    from .install import codebuddy_exe
    from . import launch
    try: return launch.command(codebuddy_exe(), '@tencent-ai/codebuddy-code', 'codebuddy')
    except ValueError as exc: raise ProviderError(str(exc))


AUTH_HINT = ('宿主CLI鉴权失败；桌面已登录不代表CLI可用。若当前lite构建没有登录入口，请配置自己的OpenAI兼容API'
             '（程序不会自动换用其他账号或API）：\n'
             '1. 新建 ~/.hyperthymesia/config.toml（Windows 为 %USERPROFILE%\\.hyperthymesia\\config.toml），写入：\n'
             '   [writer]\n   provider = "openai"\n   model = "deepseek-chat"\n'
             '   base_url = "https://api.deepseek.com/v1"\n   api_key_env = "DEEPSEEK_API_KEY"\n'
             '   （换成你的服务商的地址和模型；文件里只写环境变量名，不写 key）\n'
             '2. 把 key 放进该环境变量：Windows 执行 setx DEEPSEEK_API_KEY "你的key"；Mac/Linux 写进 shell 配置。之后完全退出并重开宿主。\n'
             '3. 执行 hyperthymesia doctor 确认“写入提供方 openai、key 环境变量已设置”，再执行 hyperthymesia write。')


def _failure_hint(text):
    value = str(text).lower()
    if any(x in value for x in ('authentication required', 'not logged in', 'unauthorized', 'please use /login')):
        return AUTH_HINT
    if 'sdk_worker_removed' in value or 'sdk_invalid_args' in value:
        return 'Qoder SDK启动模式与CLI调用不兼容；请检查CLI入口及SDK环境变量，不要直接认定所有新版CLI都需要降级。'
    if 'cannot find module' in value or 'module_not_found' in value:
        return 'CLI启动入口或构建类型不匹配；请检查实际JavaScript入口、Node.js和WorkBuddy lite构建。'
    if 'failed to extract' in value or "no module named '_socket'" in value:
        return '程序解包失败；请检查TEMP/TMP目录可写性和剩余空间。'
    from .redact import redact
    return redact(str(text))[0][:300]


def _result_object(result, label):
    text = (result.stdout or '').lstrip('\ufeff').strip()
    if result.returncode: raise ProviderError(label + '调用失败：' + _failure_hint((result.stderr or '') + '\n' + text))
    if text.lower().startswith(('authentication required', 'unauthorized', 'please use /login')):
        raise ProviderError(_failure_hint(text))
    try: obj = json.loads(text)
    except ValueError:
        lines = [line for line in text.splitlines() if line.lstrip().startswith('{')]
        try: obj = json.loads(lines[-1])
        except (ValueError, IndexError): raise ProviderError(label + '输出不是结果JSON：' + _failure_hint(result.stderr or text))
    credits = None
    if isinstance(obj, list):
        credits = sum(((x.get('providerData') or {}).get('rawUsage') or {}).get('credit') or 0 for x in obj if isinstance(x, dict))
        obj = next((x for x in reversed(obj) if isinstance(x, dict) and x.get('type') in ('result', 'error')), None)
    if not isinstance(obj, dict) or 'result' not in obj or obj.get('is_error') or obj.get('type') == 'error' or str(obj.get('subtype', '')).startswith('error'):
        raise ProviderError(label + '未返回成功结果：' + _failure_hint(obj.get('errors') or obj.get('result') or obj.get('error') or '' if isinstance(obj, dict) else ''))
    value = obj['result']
    if not isinstance(value, str): raise ProviderError(label + '结果正文类型错误')
    if value.lower().startswith(('authentication required', 'unauthorized', 'please use /login')): raise ProviderError(_failure_hint(value))
    return obj, credits


def _codebuddy(home, system, prompt, sid, log):
    cmd0 = codebuddy_cmd()
    if not cmd0: raise ProviderError('找不到WorkBuddy/CodeBuddy CLI；非默认路径可设置HYPERTHYMESIA_CODEBUDDY_CLI为实际入口文件。')
    chosen = model()
    cmd = cmd0 + ['-p', '--output-format', 'json', '--tools', '', '--strict-mcp-config', '--system-prompt', system] + \
          (['--model', chosen] if chosen else []) + (['--resume', sid] if sid else [])
    with cli_slot(home, 'codebuddy'):
        result = _run_cli(cmd, agent='codebuddy', input=prompt, capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=_workdir(home), timeout=1800)
        if result.returncode and 'EADDRINUSE' in (result.stderr or '') + (result.stdout or ''):
            # 锁外的其他程序（如宿主自身）也可能占着CLI的本地端口：退避后只重试一次，仍失败照常报错。
            log.append({'step': 'cli_port_busy_retry'}); time.sleep(5)
            result = _run_cli(cmd, agent='codebuddy', input=prompt, capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=_workdir(home), timeout=1800)
    obj, credit = _result_object(result, 'codebuddy')
    usage = obj.get('usage') or {}
    return Reply(obj.get('session_id') or sid, obj['result'],
                 {'input_tokens': usage.get('input_tokens', 0), 'cached_input_tokens': usage.get('cache_read_input_tokens', 0), 'output_tokens': usage.get('output_tokens', 0), 'cost': credit})


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
    r = _run_cli(cmd, input=prompt, capture_output=True, text=True, encoding='utf-8', errors='replace',
                       cwd=_workdir(home), timeout=1800)
    if r.returncode: raise ProviderError('%s 调用失败：%s' % (cmd[0], (r.stderr or r.stdout)[-400:]))
    return r.stdout


def qodercli_cmd():
    from . import launch
    try: return launch.command(shutil.which('qodercli'), '@qoder-ai/qodercli', 'qodercli')
    except ValueError as exc: raise ProviderError(str(exc))


def _qoder(home, system, prompt, sid, log):
    cmd0 = qodercli_cmd()
    if not cmd0: raise ProviderError('找不到qodercli；请安装官方命令行并执行qodercli login。')
    chosen = model()
    cmd = cmd0 + ['-p', '-o', 'json', '--tools', '', '--strict-mcp-config', '--system-prompt', system] + \
          (['--model', chosen] if chosen else []) + (['--resume', sid] if sid else [])
    result = _run_cli(cmd, agent='qoder', input=prompt, capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=_workdir(home), timeout=1800)
    obj, _ = _result_object(result, 'qodercli')
    usage = obj.get('usage') or {}; cached = usage.get('cache_read_input_tokens', 0)
    return Reply(obj.get('session_id') or sid, obj['result'],
                 {'input_tokens': usage.get('input_tokens', 0) + cached + usage.get('cache_creation_input_tokens', 0), 'cached_input_tokens': cached,
                  'output_tokens': usage.get('output_tokens', 0), 'cost': obj.get('total_credits'),
                  'usage_status': 'reported' if usage.get('input_tokens', 0) > 0 and usage.get('output_tokens', 0) > 0 else 'unknown'})


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
