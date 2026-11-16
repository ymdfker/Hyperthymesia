"""Recover only uniquely matched turns with explicit completion evidence; no model or guessed completion."""
import json,time
from pathlib import Path
from .importer import _text


def completed_turns(path, agent):
    current = None; completed = []
    with Path(path).open(encoding='utf-8-sig', errors='replace') as stream:
        for line in stream:
            try: event = json.loads(line)
            except ValueError: continue
            typ = event.get('type'); message = event.get('message') or {}; payload = event.get('payload') or {}
            user = None; reply = None; terminal = False
            if agent == 'codex':
                if typ == 'event_msg' and payload.get('type') == 'user_message': user = payload.get('message')
                if typ == 'event_msg' and payload.get('type') == 'task_complete': reply = payload.get('last_agent_message'); terminal = True
            elif agent == 'codebuddy':
                if typ == 'message' and event.get('role') == 'user': user = _text(event.get('content'))
                if typ == 'message' and event.get('role') == 'assistant':
                    reply = _text(event.get('content')); terminal = event.get('status') == 'completed' or message.get('stop_reason') == 'end_turn'
            elif agent in ('claude', 'qoder'):
                if typ == 'user' and not event.get('isMeta'):
                    content = message.get('content')
                    if not (isinstance(content, list) and any(x.get('type') == 'tool_result' for x in content if isinstance(x, dict))): user = _text(content)
                if typ == 'assistant':
                    reply = _text(message.get('content')); terminal = message.get('stop_reason') == 'end_turn'
                if typ == 'result' and event.get('subtype') == 'success' and not event.get('is_error'):
                    reply = event.get('result'); terminal = True
            if user is not None and user.strip():
                current = {'user': user, 'reply': '', 'complete': False}; completed.append(current)
            if reply and current is not None:
                current['reply'] = reply
                current['complete'] = terminal
    return completed


def recover_pending(state, payload, agent, log):
    sid = payload.get('session_id'); path = payload.get('transcript_path')
    if sid and path:
        state.execute('INSERT OR IGNORE INTO backlog_capture(session,turn,transcript,agent) SELECT session,turn,?,? FROM backlog WHERE session=? AND completed_at IS NULL', (path,agent,sid))
        state.execute('UPDATE backlog_capture SET transcript=? WHERE session=? AND (transcript IS NULL OR transcript=\'\')', (path,sid))
    rows = state.execute('SELECT b.*, c.transcript,c.agent FROM backlog b LEFT JOIN backlog_capture c ON b.session=c.session AND b.turn=c.turn WHERE b.completed_at IS NULL AND b.written=0').fetchall()
    parsed = {}; recovered = 0
    for row in rows:
        if not row['transcript'] or not row['agent'] or row['agent'] == 'dsh': continue
        key = (row['transcript'], row['agent'])
        if key not in parsed:
            try: parsed[key] = completed_turns(*key)
            except (OSError, ValueError, TypeError): parsed[key] = []
        matches = [turn for turn in parsed[key] if turn['user'].strip() == (row['user_text'] or '').strip()]
        # Repeated identical prompts, intermediate replies, truncated logs: keep pending, never guess.
        if len(matches) != 1 or not matches[0]['complete'] or not matches[0]['reply']: continue
        state.execute('UPDATE backlog SET assistant_text=?,completed_at=? WHERE session=? AND turn=? AND completed_at IS NULL',
                      (matches[0]['reply'],time.strftime('%Y-%m-%dT%H:%M:%S'),row['session'],row['turn']))
        recovered += 1
    if rows: log('pending_turns', json.dumps({'recovered':recovered,'still_incomplete':len(rows)-recovered}))
