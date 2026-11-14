"""Minimal stdio MCP transport for the per-session workspace tool broker.

No project modules or experiment state are loaded in this process.
"""
import json
import os
import sys
import urllib.request


def dispatch(message):
    method = message.get('method', '')
    params = message.get('params', {})
    if method == 'initialize':
        return {'protocolVersion': params.get('protocolVersion', '2024-11-05'),
                'capabilities': {'tools': {}}, 'serverInfo': {'name': 'workspace', 'version': '1.0'}}
    if method == 'ping':
        return {}
    if method == 'tools/list':
        body = {'method': 'list'}
    elif method == 'tools/call':
        body = {'method': 'call', 'name': params.get('name'), 'arguments': params.get('arguments', {})}
    elif method in ('resources/list', 'resources/templates/list', 'prompts/list'):
        return { {'resources/list': 'resources', 'resources/templates/list': 'resourceTemplates', 'prompts/list': 'prompts'}[method]: []}
    else:
        raise ValueError('Method unavailable')
    request = urllib.request.Request(os.environ['WORKSPACE_TOOL_URL'], data=json.dumps(body).encode(),
        headers={'Authorization': 'Bearer ' + os.environ['WORKSPACE_TOOL_TOKEN'], 'Content-Type': 'application/json'})
    # Loopback traffic must not use an inherited HTTP proxy.
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=30) as response:
        return json.load(response)


def main():
    for line in sys.stdin:
        try:
            message = json.loads(line)
            if 'id' not in message:
                continue
            try:
                reply = {'jsonrpc': '2.0', 'id': message['id'], 'result': dispatch(message)}
            except Exception:
                reply = {'jsonrpc': '2.0', 'id': message['id'], 'error': {'code': -32602, 'message': 'Workspace request failed'}}
            print(json.dumps(reply, ensure_ascii=False), flush=True)
        except ValueError:
            print(json.dumps({'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'Invalid JSON'}}), flush=True)


if __name__ == '__main__':
    main()
