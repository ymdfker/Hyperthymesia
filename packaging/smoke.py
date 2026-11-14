"""打包产物冒烟测试（CI 中对每个平台的可执行文件运行）：不调用任何模型，只验证可执行文件本身能工作。
用法：python packaging/smoke.py <可执行文件路径>"""
import json, os, subprocess, sys, tempfile
from pathlib import Path

exe = str(Path(sys.argv[1]).resolve())
tmp = Path(tempfile.mkdtemp())
env = dict(os.environ, AGENT_MEMORY_HOME=str(tmp / 'home'), HOME=str(tmp / 'userhome'), USERPROFILE=str(tmp / 'userhome'))
(tmp / 'userhome').mkdir()
proj = tmp / 'proj'; proj.mkdir(); (proj / 'config.py').write_text('PAGE = 10\n', encoding='utf-8')


def run(args, inp=None, cwd=None):
    r = subprocess.run([exe] + args, input=inp, capture_output=True, text=True, encoding='utf-8', env=env, cwd=cwd or str(tmp), timeout=120)
    print('$ agent-memory', ' '.join(args), '->', r.returncode)
    if r.returncode != 0: print(r.stdout, r.stderr); sys.exit('失败：' + ' '.join(args))
    return r.stdout


# 1. 版本与帮助
assert run(['--version']).strip(); assert 'serve' in run(['--help'])
# 2. MCP 握手与工具列表
out = run(['serve'], '\n'.join(json.dumps(x) for x in [
    {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18'}},
    {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
    {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'memory_read_objects', 'arguments': {'object_ids': ['u1']}}}]) + '\n', cwd=str(proj))
resp = [json.loads(l) for l in out.splitlines()]
assert [r['id'] for r in resp] == [1, 2, 3], resp
assert resp[1]['result']['tools'][0]['name'] == 'memory_read_objects'
# 3. 钩子：一轮开始/结束，记下改动（单文件内的 SQLite、改动快照、中文都要正常）
d = {'session_id': 's1', 'cwd': str(proj), 'prompt': '分页改成20'}
run(['hook', 'prompt-submit', '--agent', 'claude'], json.dumps(d, ensure_ascii=False))
(proj / 'config.py').write_text('PAGE = 20\n', encoding='utf-8')
run(['hook', 'stop', '--agent', 'claude'], json.dumps({'session_id': 's1', 'cwd': str(proj), 'last_assistant_message': '已改'}, ensure_ascii=False))
import sqlite3
row = sqlite3.connect(str(tmp / 'home' / 'state.db')).execute('SELECT user_text, assistant_text, diff FROM backlog').fetchone()
assert row[0] == '分页改成20' and row[1] == '已改' and '+PAGE = 20' in row[2], row
assert not (tmp / 'home' / 'logs' / 'hooks.log').exists(), (tmp / 'home' / 'logs' / 'hooks.log').read_text(encoding='utf-8')
# 4. 安装/卸载（临时用户目录）
run(['install', 'claude']); s = json.loads((tmp / 'userhome' / '.claude' / 'settings.json').read_text(encoding='utf-8'))
assert 'hook stop --agent claude' in json.dumps(s), s
run(['uninstall', 'claude']); assert 'hooks' not in json.loads((tmp / 'userhome' / '.claude' / 'settings.json').read_text(encoding='utf-8'))
print('冒烟测试通过')
