"""ok-script MCP 本地客户端（不依赖 GUI，直接走 streamable-http JSON-RPC）。

服务端启动方式：
    .venv\\Scripts\\python.exe -m ok mcp --config src.config:config
连接信息（url + bearer token）写在 logs/mcp/connection.json。

用法：
    # 列出 MCP 工具
    .venv\\Scripts\\python.exe tools\\mcp_cli.py tools

    # 调用任意工具，参数为 JSON
    .venv\\Scripts\\python.exe tools\\mcp_cli.py call list_tasks
    .venv\\Scripts\\python.exe tools\\mcp_cli.py call screenshot

    # 运行任务文件（服务端自动 reset -> verify -> run）并等待结果
    .venv\\Scripts\\python.exe tools\\mcp_cli.py task src\\tasks\\MyOneTimeTask.py
"""

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONNECTION_FILE = PROJECT_ROOT / "logs" / "mcp" / "connection.json"
PROTOCOL_VERSION = "2025-06-18"


def load_connection(url=None, token=None):
    if url and token:
        return url, token
    if not CONNECTION_FILE.exists():
        raise SystemExit(f"找不到 {CONNECTION_FILE}，请先启动 MCP 服务：python -m ok mcp --config src.config:config")
    data = json.loads(CONNECTION_FILE.read_text(encoding="utf-8"))
    return url or data["url"], token or data["token"]


def parse_payload(result):
    """把 tools/call 的返回转成 Python 对象：优先 structuredContent，其次 JSON 文本。"""
    if not isinstance(result, dict):
        return result
    structured = result.get("structuredContent")
    if structured:
        return structured
    texts = [block.get("text", "") for block in result.get("content") or [] if block.get("type") == "text"]
    raw = "\n".join(texts)
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return raw


class McpHttpClient:
    """极简 MCP streamable-http 客户端（initialize + tools/call）。"""

    def __init__(self, url, token):
        self.url = url
        self.token = token
        self.session_id = None
        self.protocol_version = PROTOCOL_VERSION
        self._next_id = 0
        self._http = httpx.Client(timeout=httpx.Timeout(600.0, connect=10.0))

    # ------------------------------------------------------------------ transport
    def _headers(self):
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        if self.protocol_version:
            headers["mcp-protocol-version"] = self.protocol_version
        return headers

    @staticmethod
    def _decode(response):
        content_type = response.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            messages = []
            for line in response.text.splitlines():
                if line.startswith("data:"):
                    chunk = line[5:].strip()
                    if chunk:
                        messages.append(json.loads(chunk))
            return messages
        if not response.text.strip():
            return []
        return [response.json()]

    def _send(self, payload, wait_response=True):
        response = self._http.post(self.url, headers=self._headers(), json=payload)
        session_id = response.headers.get("mcp-session-id")
        if session_id:
            self.session_id = session_id
        if response.status_code >= 400:
            raise RuntimeError(f"MCP HTTP {response.status_code}: {response.text[:500]}")
        messages = self._decode(response) if wait_response else []
        if not wait_response:
            return None
        for message in messages:
            if message.get("id") == payload.get("id"):
                if "error" in message:
                    error = message["error"]
                    raise RuntimeError(f"MCP 错误 {error.get('code')}: {error.get('message')} {error.get('data')}")
                return message.get("result")
        return None

    def request(self, method, params=None):
        self._next_id += 1
        payload = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            payload["params"] = params
        return self._send(payload, wait_response=True)

    def notify(self, method, params=None):
        payload = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        self._send(payload, wait_response=False)

    # ------------------------------------------------------------------ MCP 操作
    def initialize(self):
        result = self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "ok-script-local-cli", "version": "1.0"},
        })
        if result and result.get("protocolVersion"):
            self.protocol_version = result["protocolVersion"]
        self.notify("notifications/initialized")
        return result

    def list_tools(self):
        return self.request("tools/list", {})

    def call_tool(self, name, arguments=None):
        result = self.request("tools/call", {"name": name, "arguments": arguments or {}})
        if isinstance(result, dict) and result.get("isError"):
            raise RuntimeError(f"工具 {name} 返回错误：{parse_payload(result)}")
        return parse_payload(result)

    def close(self):
        try:
            self._http.delete(self.url, headers=self._headers())
        except Exception:
            pass
        self._http.close()


def cmd_tools(client):
    for tool in client.list_tools().get("tools", []):
        first_line = (tool.get("description") or "").splitlines()[0][:100]
        print(f"- {tool['name']}: {first_line}")


def cmd_call(client, name, raw_args):
    args = json.loads(raw_args) if raw_args else {}
    result = client.call_tool(name, args)
    print(json.dumps(result, ensure_ascii=False, indent=2) if isinstance(result, (dict, list)) else result)


def cmd_task(client, file_path, timeout, poll):
    target = Path(file_path)
    if not target.is_absolute():
        target = (Path.cwd() / target).resolve()
    if not target.exists():
        raise SystemExit(f"任务文件不存在: {target}")
    started = client.call_tool("run_task", {"file_path": str(target)})
    print(json.dumps(started, ensure_ascii=False, indent=2))
    run_id = started.get("run_id") if isinstance(started, dict) else None
    if not run_id:
        return
    status = {}
    deadline = time.time() + timeout
    last_state = None
    while time.time() < deadline:
        status = client.call_tool("get_run_status", {"run_id": run_id}) or {}
        state = status.get("state")
        if state != last_state:
            print(json.dumps(status, ensure_ascii=False, indent=2))
            last_state = state
        if state in ("succeeded", "failed", "cancelled"):
            break
        time.sleep(poll)
    log_path = status.get("log_path") if isinstance(status, dict) else None
    if log_path and Path(log_path).exists():
        print("\n===== run.log 末尾 =====")
        print("\n".join(Path(log_path).read_text(encoding="utf-8", errors="replace").splitlines()[-80:]))
    if isinstance(status, dict) and status.get("error"):
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="ok-script MCP 本地客户端")
    parser.add_argument("--url")
    parser.add_argument("--token")
    parser.add_argument("--timeout", type=float, default=900)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("tools")
    p_call = sub.add_parser("call")
    p_call.add_argument("name")
    p_call.add_argument("args", nargs="?", default="")
    p_task = sub.add_parser("task")
    p_task.add_argument("file_path")
    p_task.add_argument("--poll", type=float, default=2.0)
    args = parser.parse_args()

    url, token = load_connection(args.url, args.token)
    client = McpHttpClient(url, token)
    try:
        client.initialize()
        if args.command == "tools":
            cmd_tools(client)
        elif args.command == "call":
            cmd_call(client, args.name, args.args)
        elif args.command == "task":
            cmd_task(client, args.file_path, args.timeout, args.poll)
    finally:
        client.close()


if __name__ == "__main__":
    main()
