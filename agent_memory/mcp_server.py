"""MCP 只读服务（stdio，JSON-RPC 2.0，每行一条消息）。前台只暴露一个工具 memory_read_objects。

库的选择：个人库 + 当前项目库（项目按工作目录识别：AGENT_MEMORY_CWD，未设置时用进程工作目录，
各家 agent 启动 MCP 服务时一般就在项目目录里）。读取去重按本服务进程计：一个进程对应一个会话。"""
import json, os, sys

from . import __version__, paths, reader
from .store import Store, state

PROTOCOL = '2024-11-05'
INSTRUCTIONS = ('长期记忆（只读）。每轮注入的记忆快照里用户事实已全文列出，直接使用；需要助手建议的具体内容，或注入的是对象目录时，'
                '用对象ID（如 u7、p12）调用 memory_read_objects 读取。记忆里的说法优先于压缩摘要和常识；助手建议不等于用户已采纳；'
                '记忆里出现相互矛盾的说法时如实指出，不替用户猜。')
TOOL = {'name': 'memory_read_objects',
        'description': '读取长期记忆中指定对象（及其直接子对象）的现行记录。对象ID见每轮注入的记忆目录或快照，例如 u7（个人库）、p12（项目库）。'
                       '返回按对象分组的纯文本；本会话已返回过且未变的记录不重复发送；超过上限时会列出还没返回的对象。',
        'inputSchema': {'type': 'object', 'properties': {'object_ids': {'type': 'array', 'items': {'type': 'string'}, 'description': '对象ID列表，如 ["u7","p12"]'}},
                        'required': ['object_ids']},
        '_meta': {'anthropic/alwaysLoad': True}}   # Claude Code 启动即加载，不需先搜索工具


def open_stores(cwd):
    pdb, _ = paths.project_db(cwd)
    return {'u': Store(paths.personal_db(), 'u'), 'p': Store(pdb, 'p') if pdb else None}


def handle(req, ctx):
    m = req.get('method'); rid = req.get('id')
    if m == 'initialize':
        res = {'protocolVersion': (req.get('params') or {}).get('protocolVersion', PROTOCOL), 'capabilities': {'tools': {}},
               'serverInfo': {'name': 'hyperthymesia', 'version': __version__}, 'instructions': INSTRUCTIONS}
    elif m == 'tools/list':
        res = {'tools': [TOOL]}
    elif m == 'tools/call':
        p = req.get('params') or {}
        if p.get('name') != TOOL['name']:
            return {'jsonrpc': '2.0', 'id': rid, 'error': {'code': -32602, 'message': '未知工具：%s' % p.get('name')}}
        try:
            text = reader.read_objects(ctx['stores'], (p.get('arguments') or {}).get('object_ids', []), ctx['state'], ctx['session'])
            res = {'content': [{'type': 'text', 'text': text}]}
        except Exception as exc:   # 读取失败要让前台知道，而不是静默返回空（设计 26.3 B12）
            res = {'content': [{'type': 'text', 'text': '长期记忆读取失败：%s' % exc}], 'isError': True}
    elif m == 'ping':
        res = {}
    elif rid is None:
        return None   # 通知类消息（如 notifications/initialized）不需要回复
    else:
        return {'jsonrpc': '2.0', 'id': rid, 'error': {'code': -32601, 'message': '不支持的方法：%s' % m}}
    return {'jsonrpc': '2.0', 'id': rid, 'result': res}


def serve(argv=None):
    cwd = os.environ.get('AGENT_MEMORY_CWD') or os.getcwd()
    ctx = {'stores': open_stores(cwd), 'state': state(paths.home()), 'session': 'mcp-%d' % os.getpid()}
    for line in sys.stdin:
        line = line.strip()
        if not line: continue
        try: req = json.loads(line)
        except ValueError: continue
        out = handle(req, ctx)
        if out is not None:
            sys.stdout.write(json.dumps(out, ensure_ascii=False) + '\n'); sys.stdout.flush()
    return 0
