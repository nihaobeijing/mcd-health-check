#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""麦门健康体检官 · MCP 取数器

直接从麦当劳 MCP Server 拉取体检所需的全部工具返回，落盘到 raw/ 目录，
供 health_report.py 做统计与渲染。

用法：
    export MCD_TOKEN=你的Token
    python3 scripts/fetch_raw.py --out raw
    python3 scripts/fetch_raw.py --out raw --token 你的Token

Token 读取顺序：--token > 环境变量 MCD_TOKEN > ~/.mcd_mcp_token > ./.mcd_token

说明：
- 接入地址是 https://mcp.mcd.cn 根路径。官方文档里写的 https://mcp.mcd.cn/mcp
  在当前服务端会返回 404，本脚本会自动回退。
- 本脚本只调用只读工具，不会领券、抽奖、下单或产生任何消耗。
"""
import argparse
import json
import os
import urllib.error
import urllib.request

DEFAULT_URL = "https://mcp.mcd.cn"
PROTOCOL_VERSION = "2025-06-18"

# 体检所需的只读工具：(工具名, 是否必需, 参数)
READONLY_TOOLS = [
    ("now-time-info", True, {}),
    ("order-list", True, {}),
    ("list-nutrition-foods", True, {}),
    ("query-my-account", True, {}),
    ("query-my-coupons", True, {}),
    ("mall-order-list", True, {}),
    ("query-lottery-info", False, {}),
    ("campaign-calendar", False, {}),
]


class McpClient:
    """最小可用的 MCP Streamable HTTP 客户端。"""

    def __init__(self, url, token):
        self.url = url.rstrip("/")
        self.token = token
        self.session_id = None
        self._id = 0

    def _headers(self):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": "Bearer %s" % self.token,
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        return headers

    def _post(self, payload):
        request = urllib.request.Request(
            self.url, data=json.dumps(payload).encode(), headers=self._headers(), method="POST"
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            if not self.session_id:
                self.session_id = response.headers.get("Mcp-Session-Id")
            body = response.read().decode("utf-8", errors="replace")
        body = body.strip()
        if not body:
            return None
        if body.startswith("{"):
            return json.loads(body)
        for line in body.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        return None

    def _rpc(self, method, params=None):
        self._id += 1
        return self._post({
            "jsonrpc": "2.0",
            "id": self._id,
            "method": method,
            "params": params or {},
        })

    def initialize(self):
        result = self._rpc("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "mcd-health-check", "version": "1.0.0"},
        })
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        return result

    def list_tools(self):
        result = self._rpc("tools/list")
        return (result or {}).get("result", {}).get("tools", [])

    def call_tool(self, name, arguments=None):
        return self._rpc("tools/call", {"name": name, "arguments": arguments or {}})


def tool_text(result):
    """把 MCP 工具返回的内容拼成纯文本。"""
    if not result:
        return ""
    if "error" in result:
        return json.dumps(result, ensure_ascii=False, indent=2)
    payload = result.get("result") or {}
    chunks = []
    for item in payload.get("content", []) or []:
        if item.get("type") == "text":
            chunks.append(item.get("text", ""))
        else:
            chunks.append(json.dumps(item, ensure_ascii=False))
    if not chunks and payload:
        chunks.append(json.dumps(payload, ensure_ascii=False, indent=2))
    return "\n".join(chunks)


def resolve_token(cli_token):
    if cli_token:
        return cli_token.strip()
    for env in ("MCD_TOKEN", "MCD_MCP_TOKEN"):
        value = os.environ.get(env)
        if value:
            return value.strip()
    for path in (os.path.expanduser("~/.mcd_mcp_token"), ".mcd_token"):
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as fh:
                value = fh.read().strip()
            if value:
                return value
    return ""


def connect(url, token):
    """连接 MCP Server，根路径失败时回退到 /mcp。"""
    errors = []
    for candidate in (url, url + "/mcp"):
        client = McpClient(candidate, token)
        try:
            client.initialize()
            tools = client.list_tools()
            if tools:
                return client, candidate
            errors.append("%s → 握手成功但没有工具" % candidate)
        except urllib.error.HTTPError as exc:
            errors.append("%s → HTTP %d" % (candidate, exc.code))
        except Exception as exc:  # 网络层异常
            errors.append("%s → %s" % (candidate, exc))
    raise SystemExit("连接失败：\n  " + "\n  ".join(errors))


def main():
    parser = argparse.ArgumentParser(description="麦门健康体检官 · MCP 取数器")
    parser.add_argument("--out", default="raw", help="原始返回落盘目录，默认 raw")
    parser.add_argument("--url", default=os.environ.get("MCD_URL", DEFAULT_URL), help="MCP Server 地址")
    parser.add_argument("--token", default="", help="MCP Token，优先于环境变量")
    parser.add_argument("--list-tools", action="store_true", help="只打印服务端工具列表")
    args = parser.parse_args()

    token = resolve_token(args.token)
    if not token:
        raise SystemExit(
            "没有找到 MCP Token。请设置环境变量 MCD_TOKEN，或用 --token 传入，"
            "或写入 ~/.mcd_mcp_token 文件。\n"
            "Token 申请地址：https://open.mcd.cn/mcp"
        )

    client, endpoint = connect(args.url, token)
    print("已连接 MCP Server: %s" % endpoint)

    if args.list_tools:
        for tool in client.list_tools():
            print("- %s: %s" % (tool.get("name"), (tool.get("description") or "").strip().splitlines()[0]))
        return

    available = {tool.get("name") for tool in client.list_tools()}
    os.makedirs(args.out, exist_ok=True)
    saved, skipped = [], []
    for name, required, arguments in READONLY_TOOLS:
        if name not in available:
            skipped.append(name)
            continue
        text = tool_text(client.call_tool(name, arguments))
        if not text:
            skipped.append(name)
            continue
        path = os.path.join(args.out, name + ".txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        saved.append(name)
        print("  ✓ %-24s %d 字符" % (name, len(text)))

    if skipped:
        print("  ! 未取到：%s" % "、".join(skipped))
    if not saved:
        raise SystemExit("没有取到任何工具返回，请检查 Token 权限。")
    print("原始数据已保存到 %s/ ，下一步运行 scripts/health_report.py" % os.path.abspath(args.out))


if __name__ == "__main__":
    main()
