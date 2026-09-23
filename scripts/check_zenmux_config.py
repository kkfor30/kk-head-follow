#!/usr/bin/env python3
"""Check ZenMux environment configuration without exposing the API key."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

from zenmux_config import configured_api_key, config_path


DEFAULT_BASE_URL = "https://zenmux.ai/api/v1"
DOCS_URL = "https://zenmux.ai/docs/guide/quickstart"


def configure_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass


def result(ok: bool, status: str, **details: Any) -> dict[str, Any]:
    return {"ok": ok, "status": status, **details}


def check_api(base_url: str, api_key: str) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/models",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return result(True, "reachable", httpStatus=response.status, endpoint=f"{base_url.rstrip('/')}/models")
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            return result(False, "rejected", httpStatus=exc.code, message="API Key 无效、已禁用或没有当前模型权限")
        return result(False, "api-error", httpStatus=exc.code, message="ZenMux API 返回了错误状态")
    except urllib.error.URLError as exc:
        return result(False, "network-error", message=f"无法连接 ZenMux：{exc.reason}")


def print_human(check: dict[str, Any], env_name: str, base_url: str) -> None:
    if check["ok"]:
        print("ZenMux 配置已检测到。")
        print(f"API endpoint: {base_url}")
        if check["status"] != "reachable":
            print("提示：这里只确认了环境变量存在；需要实际调用时再验证 API 权限。")
        return

    print(f"未检测到可用的 ZenMux 配置：{check.get('message', '未知错误')}")
    print()
    print("配置位置：")
    print("1. 登录 ZenMux 控制台，在 Subscription 或 Pay As You Go 的 API Keys 页面创建 API Key。")
    print(f"2. 将 Key 配置为环境变量：{env_name}")
    print(f'   当前 PowerShell 会话：$env:{env_name} = "<your-key>"')
    print(f'   当前用户永久配置：[Environment]::SetEnvironmentVariable("{env_name}", "<your-key>", "User")')
    print("3. 重新打开终端，再运行本检查脚本或生成命令。")
    print(f"官方说明：{DOCS_URL}")


def main() -> int:
    configure_output()
    parser = argparse.ArgumentParser(description="Check ZenMux API configuration")
    parser.add_argument("--env-var", default="ZENMUX_API_KEY")
    parser.add_argument("--base-url", default=os.environ.get("ZENMUX_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--check-api", action="store_true", help="also make a read-only models request")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    if args.env_var != "ZENMUX_API_KEY":
        api_key = os.environ.get(args.env_var, "").strip()
        source = args.env_var if api_key else ""
    else:
        api_key, source = configured_api_key()
    if not api_key:
        check = result(False, "missing", envVar=args.env_var, message=f"缺少环境变量 {args.env_var}")
    elif args.check_api:
        check = check_api(args.base_url, api_key)
        check.update({"envVar": args.env_var, "keyPresent": True, "source": source})
    else:
        check = result(True, "present", envVar=args.env_var, keyPresent=True, source=source)

    if args.as_json:
        print(json.dumps(check, ensure_ascii=False, indent=2))
    else:
        print_human(check, args.env_var, args.base_url)
        if not check["ok"]:
            print(f"本地配置路径：{config_path()}")
            print("可用隐藏输入安全保存：python scripts/zenmux_config.py set")
    return 0 if check["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
