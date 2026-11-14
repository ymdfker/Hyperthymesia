"""CodeBuddy（WorkBuddy 内置）端到端：由 claude_e2e.py 改写。真实钩子 + MCP + 后台写入，全在一个临时测试项目里（install --project，只改该项目的配置）。

  python3 bench/claude_e2e.py <测试目录>
流程：复制编程场景仓库为测试项目（git 仓库）→ install claude --project → Claude Code 跑编码轮次（同一会话）
→ 等后台写入完成 → 新会话提问。记忆库放在 <测试目录>/home（AGENT_MEMORY_HOME），不碰用户自己的记忆和配置。"""
import json, os, shutil, subprocess, sys, time, uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TEMPLATE = Path.home() / 'Documents/projects/agent-memtest/codex_idx/scenario_code/repo_template'
ROUNDS = [
    'Add a `remove` subcommand to the CLI in repo that deletes an item by name, with unit tests. Our error codes are always prefixed INV-.',
    "When `list` is called without --limit it should use a default page size. Choose the value yourself and put it in inventory/config.py. Reply with only the word done.",
    'Set up file logging in inventory/log.py: choose the log file location under var/ and a rotation size and backup count yourself. Reply with only the word done.',
    'FYI our process: code reviews go to Priya, and we ship every Thursday. No code change needed, just acknowledge.',
]
QUESTIONS = [
    "Without looking at any files: what default page size does `list` use, and what is our error-code prefix?",
    "Where do log files go, and what are the rotation size and backup count? Answer from memory.",
    "Who reviews our PRs and on which weekday do we ship?",
]
TOOLS = 'Read,Edit,Write,Glob,Grep'


def env(home):
    e = {k: v for k, v in os.environ.items() if not k.startswith(('CLAUDE_CODE_', 'CLAUDECODE', 'MCP_', 'ANTHROPIC_CLAUDE_DESKTOP'))}
    e.update(AGENT_MEMORY_HOME=str(home), PYTHONPATH=str(REPO), MCP_CONNECTION_NONBLOCKING='false',
             AGENT_MEMORY_BACKLOG_TOKENS=os.environ.get('AGENT_MEMORY_BACKLOG_TOKENS', '1500'))
    return e


CB = '/Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/cli/bin/codebuddy'
MODEL = os.environ.get('E2E_MODEL', 'glm-5.3-flash')   # 便宜模型


def claude(proj, home, prompt, sid, first, log):
    cmd = [CB, '-p', prompt, '--model', MODEL, '--output-format', 'json', '--permission-mode', 'acceptEdits',
           '--strict-mcp-config', '--mcp-config', str(proj / '.mcp.json'), '--tools', TOOLS,
           '--allowedTools', TOOLS + ',mcp__hyperthymesia__memory_read_objects'] + (['--session-id', sid] if first else ['--resume', sid])
    for attempt in range(3):
        r = subprocess.run(cmd, cwd=proj, env=env(home), capture_output=True, text=True, timeout=1200, stdin=subprocess.DEVNULL)
        try:
            o = json.loads(r.stdout)
            if isinstance(o, list):   # CodeBuddy 的 json 输出是事件数组：取最后的 result，累加各条消息的 credit
                credit = sum(((x.get('providerData') or {}).get('rawUsage') or {}).get('credit') or 0 for x in o if isinstance(x, dict))
                o = dict(next((x for x in reversed(o) if x.get('type') == 'result'), {}), total_cost_usd=credit)
        except ValueError: o = {'is_error': True, 'result': (r.stderr or r.stdout)[-300:]}
        if not o.get('is_error'): break
        if attempt == 0 and first: cmd[cmd.index('--session-id')] = '--resume'
    log.append({'prompt': prompt[:60], 'reply': o.get('result', ''), 'cost': o.get('total_cost_usd'), 'error': o.get('is_error')})
    print(json.dumps({'prompt': prompt[:50], 'cost': o.get('total_cost_usd'), 'reply': (o.get('result') or '')[:200]}, ensure_ascii=False), flush=True)
    return o


def main():
    t = Path(sys.argv[1]).resolve(); proj = t / 'proj'; home = t / 'home'
    if not proj.exists():
        shutil.copytree(TEMPLATE, proj)
        subprocess.run(['git', 'init', '-q', str(proj)], check=True)
    subprocess.run([sys.executable, '-m', 'agent_memory', 'install', 'codebuddy', '--project', str(proj)], cwd=REPO, env=env(home), check=True)
    log = []; sid = str(uuid.uuid4())
    for i, p in enumerate(ROUNDS): claude(proj, home, p, sid, i == 0, log)
    # 会话结束：再写剩余积压（真实使用中 SessionEnd 钩子会做；-p 进程每轮结束就退出，这里手动补一次）
    for _ in range(120):
        if not list((home / 'locks').glob('*.lock')) if (home / 'locks').exists() else True: break
        time.sleep(5)
    subprocess.run([sys.executable, '-m', 'agent_memory', 'write'], cwd=REPO, env=env(home))
    sid2 = str(uuid.uuid4())
    for i, q in enumerate(QUESTIONS): claude(proj, home, q, sid2, i == 0, log)
    (t / 'log.json').write_text(json.dumps(log, ensure_ascii=False, indent=1))
    print(json.dumps({'front_credit': round(sum(x['cost'] or 0 for x in log), 3), 'model': MODEL}))


if __name__ == '__main__':
    main()
