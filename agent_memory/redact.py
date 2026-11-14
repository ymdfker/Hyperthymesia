"""Credential redaction for writer material (design 26.3 A1). Applied by the program to every text that goes to the
writer (user message, assistant reply, workspace change block) before it is sent or stored as a source segment, so a
secret never reaches the writer model, the memory store or the injected snapshot.

Two layers:
 1. known token shapes (provider keys, private keys, JWTs, URLs with a password) are replaced wherever they appear;
 2. assignments whose NAME says it holds a secret (password, secret, token, api_key, ...) get their VALUE replaced,
    unless the value is plainly not a secret (a number, a boolean, an env-var reference, an empty or placeholder value).
A replaced value becomes 〔已脱敏:kind〕, so the writer still learns that the setting exists and where it lives.
Usage: from agent_memory.redact import redact; text, hits = redact(text)"""
import re

SHAPES = [
    ('private_key', re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----', re.S)),
    ('openai_key', re.compile(r'\bsk-(?:proj-|ant-)?[A-Za-z0-9_\-]{20,}')),
    ('github_token', re.compile(r'\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}')),
    ('slack_token', re.compile(r'\bxox[abprs]-[A-Za-z0-9\-]{10,}')),
    ('aws_access_key', re.compile(r'\b(?:AKIA|ASIA)[0-9A-Z]{16}\b')),
    ('google_api_key', re.compile(r'\bAIza[0-9A-Za-z_\-]{35}\b')),
    ('stripe_key', re.compile(r'\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{16,}')),
    ('jwt', re.compile(r'\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}')),
    ('url_password', re.compile(r'(?<=://)[^\s:/@]+:[^\s@/]{3,}(?=@)')),
    ('bearer', re.compile(r'(?i)(?<=bearer )[A-Za-z0-9_\-\.=]{16,}')),
]
NAME = r'[A-Za-z0-9_\-\.]*(?:passw(?:or)?d|passwd|pwd|secret|token|api[_\-]?key|apikey|access[_\-]?key|private[_\-]?key|client[_\-]?secret|auth|credential|密码|口令|密钥|令牌)[A-Za-z0-9_\-\.]*'
ASSIGN = re.compile(r'(?i)(\b' + NAME + r'\b["\']?\s*(?:=|:|是|为)\s*)(["\']?)([^\s"\',;)}\]]{4,})(\2)')
ASSIGN_ZH = re.compile(r'((?:密码|口令|密钥|令牌|私钥|验证码)\s*(?:是|为|:|：|=)\s*)([^\s，。,;；、)）]{4,})')   # CJK has no word boundary
SAFE = re.compile(r'(?i)^(?:\d+(?:\.\d+)?|true|false|null|none|yes|no|xxx+|\*+|<[^>]+>|\$\{?[A-Z_][A-Z0-9_]*\}?|os\.environ.*|getenv.*|process\.env.*|env\(.*|your[_\-].*|changeme|placeholder|example.*|redacted.*|〔已脱敏.*)$')
SAFE_NAME = re.compile(r'(?i)(max|min)[_\-]?tokens?|tokens?[_\-]?(limit|count|budget|len|size)|token[_\-]?type|auth[_\-]?(url|method|mode|type|enabled|provider)|author')

def redact(text):
    hits = []
    if not text: return text, hits
    for kind, rx in SHAPES:
        def sub(m, kind=kind): hits.append(kind); return '〔已脱敏:%s〕' % kind
        text = rx.sub(sub, text)
    def assign(m):
        name = m.group(1); val = m.group(3)
        if SAFE.match(val) or SAFE_NAME.search(name): return m.group(0)
        hits.append('secret_assignment'); return name + m.group(2) + '〔已脱敏:secret〕' + m.group(4)
    text = ASSIGN.sub(assign, text)
    def assign_zh(m):
        if SAFE.match(m.group(2)): return m.group(0)
        hits.append('secret_assignment'); return m.group(1) + '〔已脱敏:secret〕'
    text = ASSIGN_ZH.sub(assign_zh, text)
    return text, hits

if __name__ == '__main__':
    import sys
    t, h = redact(sys.stdin.read()); sys.stdout.write(t); sys.stderr.write('hits: %s\n' % h)
