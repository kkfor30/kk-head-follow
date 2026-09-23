#!/usr/bin/env python3
"""Manage a local ZenMux API key for kk-head-follow."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any


API_KEY_ENV = "ZENMUX_API_KEY"


def config_path() -> Path:
    if os.name == "nt":
        user_config = os.environ.get("APPDATA", "").strip()
        root = Path(user_config).expanduser() if user_config else Path.home() / "AppData" / "Roaming"
        return root / "kk-head-follow" / "config.json"
    config_home = os.environ.get("XDG_CONFIG_HOME", "").strip()
    root = Path(config_home).expanduser() if config_home else Path.home() / ".config"
    return root / "kk-head-follow" / "config.json"


def read_config(path: Path | None = None) -> dict[str, Any]:
    target = path or config_path()
    if not target.exists():
        return {}
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"配置文件不是有效 JSON：{target}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"配置文件根节点必须是对象：{target}")
    return value


def configured_api_key(path: Path | None = None) -> tuple[str, str]:
    environment_key = os.environ.get(API_KEY_ENV, "").strip()
    if environment_key:
        return environment_key, API_KEY_ENV
    config = read_config(path)
    zenmux = config.get("zenmux")
    if isinstance(zenmux, dict):
        stored = zenmux.get("api_key")
        if isinstance(stored, str) and stored.strip():
            return stored.strip(), str(path or config_path())
    return "", ""


def write_config(config: dict[str, Any], path: Path | None = None) -> Path:
    target = path or config_path()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        target.parent.chmod(0o700)
    except OSError:
        pass
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        temporary.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    temporary.replace(target)
    return target


def set_key() -> int:
    key = getpass.getpass("ZenMux API Key（输入内容不会显示）：").strip()
    if not key:
        raise RuntimeError("API Key 不能为空")
    config = read_config()
    zenmux = config.get("zenmux")
    if not isinstance(zenmux, dict):
        zenmux = {}
    zenmux["api_key"] = key
    config["zenmux"] = zenmux
    print(f"已安全保存 ZenMux API Key：{write_config(config)}")
    return 0


def clear_key() -> int:
    target = config_path()
    config = read_config(target)
    zenmux = config.get("zenmux")
    if isinstance(zenmux, dict):
        zenmux.pop("api_key", None)
        if zenmux:
            config["zenmux"] = zenmux
        else:
            config.pop("zenmux", None)
    if config:
        write_config(config, target)
    elif target.exists():
        target.unlink()
    print("已清除本地保存的 ZenMux API Key")
    return 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
    parser = argparse.ArgumentParser(description="管理 kk-head-follow 的 ZenMux 配置")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("set", help="安全输入并本地保存 API Key")
    subparsers.add_parser("status", help="检查是否已配置 API Key")
    subparsers.add_parser("clear", help="清除本地保存的 API Key")
    subparsers.add_parser("path", help="显示本地配置文件路径")
    args = parser.parse_args()
    if args.command == "set":
        return set_key()
    if args.command == "clear":
        return clear_key()
    if args.command == "path":
        print(config_path())
        return 0
    _, source = configured_api_key()
    if source:
        print(f"ZenMux API Key 已配置（来源：{source}）")
        return 0
    print("ZenMux API Key 尚未配置")
    print("请运行：python scripts/zenmux_config.py set")
    print("也可在 ZenMux 控制台的 Subscription 或 Pay As You Go → API Keys 页面创建")
    print("官方说明：https://zenmux.ai/docs/guide/quickstart")
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
