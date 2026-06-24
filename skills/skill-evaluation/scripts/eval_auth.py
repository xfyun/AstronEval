#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
鉴权Token管理脚本
管理评测服务的鉴权Token，包括Token获取、缓存、检查和刷新

支持两种登录模式：
1. 手动模式（OOB）：用户手动复制授权码
2. 自动模式（Callback）：本地启动回调服务器，自动接收授权码
"""

import argparse
import json
import os
import sys
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

from utils import (
    result,
    DEFAULT_AUTH_CONFIG,
    DEFAULT_AUTH_CACHE,
    OOB_REDIRECT,
    DEFAULT_CALLBACK_HOST,
    DEFAULT_CALLBACK_PORT,
    DEFAULT_CALLBACK_TIMEOUT,
    is_expired,
    NetworkError,
)
from files import (
    load_json,
    save_json,
    load_config_yaml,
)
from clients import (
    generate_pkce_pair,
    generate_state_token,
    OAuthCallbackServer,
    AuthClient,
)


# 获取脚本所在目录，用于解析相对路径
SCRIPT_DIR = Path(__file__).parent

# 内置客户端标识（讯飞开放平台）
CALLBACK_CLIENT_ID = "eval_skill_prod_xfyun_callback"
OOB_CLIENT_ID = "eval_skill_prod_xfyun"


# ============================================================================
# 辅助函数
# ============================================================================

def _resolve_config_path(config_path: str) -> str:
    """
    解析配置文件路径。

    如果是相对路径，则相对于脚本所在目录（scripts/）解析。
    如果是绝对路径，直接使用。
    """
    p = Path(config_path)
    if p.is_absolute():
        return str(p)
    # 相对路径：相对于脚本所在目录
    return str(SCRIPT_DIR / config_path)

def _try_open_browser(url: str) -> bool:
    """
    尝试打开浏览器

    Args:
        url: 要打开的URL

    Returns:
        是否成功打开浏览器
    """
    try:
        return webbrowser.open(url)
    except Exception:
        return False


def _save_state_token(output_path: str, state_token: str,
                      client_id: str,
                      pkce_verifier: Optional[str] = None):
    """
    保存 state token 到临时文件

    Args:
        output_path: Token缓存文件路径（用于推导state文件路径）
        state_token: 状态标识
        client_id: 客户端标识
        pkce_verifier: PKCE verifier（可选）
    """
    state_path = output_path.replace("auth.json", "state.json")
    state_data = {
        "state_token": state_token,
        "client_id": client_id
    }
    if pkce_verifier:
        state_data["pkce_verifier"] = pkce_verifier
    save_json(state_path, state_data)


# ============================================================================
# Token 检查
# ============================================================================

def check_token(output_path: str) -> Dict[str, Any]:
    """检查本地Token是否有效"""
    load_result = load_json(output_path)

    if not load_result.get("success"):
        return result("check", "not_found", "Token缓存文件不存在")

    auth_cache = load_result.get("data", {})

    access_token = auth_cache.get("access_token")
    if not access_token:
        return result("check", "invalid", "Token不存在")

    expires_at = auth_cache.get("expires_at")
    if expires_at and is_expired(expires_at):
        return result("check", "invalid", "Token已过期")

    return result("check", "valid", "Token有效", {
        "access_token": access_token,
        "expires_at": expires_at
    })


# ============================================================================
# 登录URL请求
# ============================================================================

def _request_login_url(client: AuthClient, auth_init_url: str,
                       state_token: str, redirect_uri: str,
                       client_id: str,
                       pkce_challenge: Optional[str] = None) -> Tuple[str, Optional[str]]:
    """
    请求登录URL

    Args:
        client: AuthClient 实例
        auth_init_url: 认证初始化 URL
        state_token: 状态标识
        redirect_uri: 回调地址
        client_id: 客户端标识
        pkce_challenge: PKCE challenge（可选）

    Returns:
        (login_url, error_message) - 成功时error_message为None
    """
    try:
        payload = {
            "state_token": state_token,
            "redirect_uri": redirect_uri,
            "client_id": client_id
        }
        # 如果启用 PKCE，添加 challenge
        if pkce_challenge:
            payload["code_challenge"] = pkce_challenge
            payload["code_challenge_method"] = "S256"

        resp = client.request_full_url("POST", auth_init_url, json=payload)
        login_url = resp.get("login_url") if isinstance(resp, dict) else None
        if not login_url:
            return None, "未获取到登录地址"
        return login_url, None
    except NetworkError as e:
        return None, f"登录初始化失败: {e}"


# ============================================================================
# Token 换取
# ============================================================================

def exchange_token(client: AuthClient, token_url: str, code: str, state_token: str,
                   output_path: str = DEFAULT_AUTH_CACHE,
                   client_id: str = None,
                   pkce_verifier: Optional[str] = None) -> Dict[str, Any]:
    """
    使用授权码换取Token

    Args:
        client: AuthClient 实例
        token_url: Token换取 URL
        code: 授权码
        state_token: 状态标识
        output_path: Token缓存文件路径
        client_id: 客户端标识
        pkce_verifier: PKCE verifier（可选）
    """
    # 验证state_token并获取client_id
    state_path = output_path.replace('auth.json', 'state.json')
    state_result = load_json(state_path)
    cached_state = state_result.get("data") if state_result.get("success") else None
    if cached_state and cached_state.get("state_token") != state_token:
        return result("token", "error", "状态标识不匹配，可能存在CSRF攻击", success=False)

    # 从 state 文件获取 client_id，否则使用传入的值
    if not client_id:
        client_id = cached_state.get("client_id") if cached_state else None

    # 构建请求
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "state": state_token,
        "client_id": client_id
    }
    # 如果启用 PKCE，添加 verifier
    if pkce_verifier:
        payload["code_verifier"] = pkce_verifier

    # 请求Token
    try:
        resp = client.request_full_url("POST", token_url, json=payload)

        token_data = resp.get("data", resp) if isinstance(resp, dict) else resp
        access_token = token_data.get("access_token")
        if not access_token:
            return result("token", "error", "未获取到access_token", success=False)

        # 计算过期时间
        expires_in = token_data.get("expires_in", 7200)
        now = datetime.now().astimezone()
        expires_at = now + timedelta(seconds=expires_in)

        # 保存Token
        auth_cache = {
            "access_token": access_token,
            "expires_in": expires_in,
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat()
        }
        save_json(output_path, auth_cache)

        # 清理state缓存
        if os.path.exists(state_path):
            os.remove(state_path)

        return result("token", "success", "Token获取成功", {
            "access_token": access_token,
            "expires_in": expires_in,
            "created_at": auth_cache["created_at"],
            "expires_at": auth_cache["expires_at"]
        })
    except NetworkError as e:
        return result("token", "error", f"Token获取失败: {e}", success=False)


# ============================================================================
# 环境检测
# ============================================================================

def detect_browser_environment() -> Dict[str, Any]:
    """
    检测环境是否支持自动打开浏览器

    Returns:
        - can_auto: 是否支持自动模式
        - reason: 判断原因
    """
    import platform
    system = platform.system()

    # Windows/macOS 默认有图形界面
    if system in ("Windows", "Darwin"):
        return {"can_auto": True, "reason": f"{system}系统默认支持浏览器"}

    # Linux 检测显示环境
    if system == "Linux" and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return {"can_auto": False, "reason": "Linux环境无显示服务，检测为服务器终端"}

    # 尝试检测浏览器
    try:
        if webbrowser.get():
            return {"can_auto": True, "reason": "检测到可用浏览器"}
    except Exception:
        pass

    return {"can_auto": False, "reason": "无法检测到可用浏览器"}


# ============================================================================
# 回调模式登录
# ============================================================================

def auto_login(
    client: AuthClient,
    config: Dict,
    output_path: str = DEFAULT_AUTH_CACHE,
    port: int = DEFAULT_CALLBACK_PORT,
    timeout: int = DEFAULT_CALLBACK_TIMEOUT,
    use_pkce: bool = True
) -> Dict[str, Any]:
    """
    自动登录流程（回调模式）

    1. 启动本地回调服务器
    2. 请求登录URL
    3. 打开浏览器
    4. 等待回调接收授权码
    5. 换取Token并保存

    Args:
        client: AuthClient 实例
        config: 配置字典
        output_path: Token缓存文件路径
        port: 回调服务器端口
        timeout: 超时时间（秒）
        use_pkce: 是否启用PKCE

    Returns:
        result 字典
    """
    # 回调模式使用内置的 callback_client_id
    client_id = CALLBACK_CLIENT_ID

    # 生成 state token
    state_token = generate_state_token()

    # 生成 PKCE pair（可选）
    pkce_verifier = None
    pkce_challenge = None
    if use_pkce:
        pkce_verifier, pkce_challenge = generate_pkce_pair()

    # 启动回调服务器
    callback_server = OAuthCallbackServer(
        expected_state=state_token,
        host=DEFAULT_CALLBACK_HOST,
        port=port,
        timeout=timeout
    )
    start_result = callback_server.start()
    if not start_result.get("success"):
        return start_result

    redirect_uri = callback_server.redirect_uri

    try:
        # 请求登录URL
        login_url, error = _request_login_url(
            client, config["auth_init_url"], state_token, redirect_uri, client_id, pkce_challenge
        )
        if error:
            # 如果是 redirect_uri 不被接受的错误，返回特定状态以便上层回退到 OOB 模式
            if "未获取到登录地址" in error:
                return result("login", "redirect_uri_rejected", error, success=False)
            return result("login", "error", error, success=False)

        # 保存 state（用于后续验证）
        _save_state_token(output_path, state_token, client_id, pkce_verifier)

        # 打开浏览器
        browser_opened = _try_open_browser(login_url)

        if not browser_opened:
            # 浏览器未打开，返回特定状态以便上层回退到手动模式
            return result("login", "browser_failed", "无法打开浏览器", success=False)

        # 等待回调
        callback_result = callback_server.wait_for_callback()

        if not callback_result.get("success"):
            return callback_result

        # 获取授权码
        code = callback_result.get("data", {}).get("code")

        # 换取 Token
        token_result = exchange_token(
            client, config["token_url"], code, state_token, output_path, client_id, pkce_verifier
        )

        return token_result

    finally:
        callback_server.stop()


# ============================================================================
# 手动登录
# ============================================================================

def manual_login(
    client: AuthClient,
    config: Dict,
    output_path: str = DEFAULT_AUTH_CACHE
) -> Dict[str, Any]:
    """
    手动登录流程（OOB模式）

    返回登录链接，用户自行访问完成授权，适合服务器终端等无图形界面环境。

    Args:
        client: AuthClient 实例
        config: 配置字典
        output_path: Token缓存文件路径

    Returns:
        result 字典，包含 login_url 和 state_token
    """
    # 手动模式使用内置的 oob_client_id
    client_id = OOB_CLIENT_ID

    # 生成state并请求登录URL
    state_token = generate_state_token()
    login_url, error = _request_login_url(client, config["auth_init_url"], state_token, OOB_REDIRECT, client_id)
    if error:
        return result("login", "error", error, success=False)

    # 保存state
    _save_state_token(output_path, state_token, client_id)

    return result("login", "manual_url", "请访问登录链接完成授权", {
        "login_url": login_url,
        "state_token": state_token,
        "mode": "oob"
    }, success=True)


# ============================================================================
# 智能登录入口
# ============================================================================

def login(
    config_path: str,
    output_path: str = DEFAULT_AUTH_CACHE,
    force_mode: Optional[str] = None,
    use_callback: bool = True,
    callback_port: int = DEFAULT_CALLBACK_PORT
) -> Dict[str, Any]:
    """
    智能登录流程：自动选择模式并完成登录

    流程：
    1. 检测环境是否支持浏览器
    2. 若支持且 use_callback=True，使用回调模式（自动完成）
    3. 否则使用 OOB 模式（需手动输入授权码）

    Args:
        config_path: 配置文件路径（相对路径相对于 scripts/ 目录）
        output_path: Token缓存文件路径
        force_mode: 强制指定模式，"auto"或"manual"
        use_callback: 是否优先使用回调模式
        callback_port: 回调服务器端口

    Returns:
        统一 result() 格式的字典
    """
    # 解析配置文件路径（相对路径相对于脚本所在目录）
    resolved_config_path = _resolve_config_path(config_path)

    # 加载配置
    config_result = load_config_yaml(resolved_config_path)
    config = config_result.get("data", {})

    # 创建 AuthClient 实例（使用完整 URL 请求，无需 base_url）
    client = AuthClient()

    # 环境检测
    env_info = detect_browser_environment()
    can_auto = env_info["can_auto"]

    # 根据 force_mode 覆盖
    if force_mode == "auto":
        can_auto = True
    elif force_mode == "manual":
        can_auto = False

    # 选择登录模式
    if can_auto and use_callback:
        # 回调模式：自动完成整个流程
        callback_result = auto_login(
            client=client,
            config=config,
            output_path=output_path,
            port=callback_port
        )

        # 如果回调模式失败，自动回退到手动模式
        if not callback_result.get("success"):
            status = callback_result.get("status")
            if status in ("redirect_uri_rejected", "browser_failed"):
                return manual_login(
                    client=client,
                    config=config,
                    output_path=output_path
                )

        return callback_result
    else:
        # 手动模式：返回登录URL等待手动输入
        return manual_login(
            client=client,
            config=config,
            output_path=output_path
        )


# ============================================================================
# CLI 入口
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="评测服务鉴权Token管理脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 智能登录（自动选择最佳模式）
  python eval_auth.py login

  # 强制使用自动模式（回调）
  python eval_auth.py login --mode auto

  # 强制使用手动模式
  python eval_auth.py login --mode manual

  # 指定回调端口
  python eval_auth.py login --mode auto --port 8080

  # 手动输入授权码换取Token
  python eval_auth.py token --code <code> --state_token <state>

  # 检查Token有效性
  python eval_auth.py check

  # 检测浏览器环境
  python eval_auth.py detect
        """
    )
    subparsers = parser.add_subparsers(dest="command",
                                        help="可用命令")

    # detect 子命令
    detect_parser = subparsers.add_parser("detect", help="检测浏览器环境")
    detect_parser.add_argument("--output", default=DEFAULT_AUTH_CACHE,
                               help="Token缓存文件路径")

    # login 子命令
    login_parser = subparsers.add_parser("login", help="智能登录授权")
    login_parser.add_argument("--config", default=DEFAULT_AUTH_CONFIG,
                              help="鉴权配置文件路径")
    login_parser.add_argument("--output", default=DEFAULT_AUTH_CACHE,
                              help="Token缓存文件路径")
    login_parser.add_argument("--mode", choices=["auto", "manual"],
                              default=None, help="登录模式：auto(自动) 或 manual(手动)，默认自动选择")
    login_parser.add_argument("--port", type=int, default=DEFAULT_CALLBACK_PORT,
                              help=f"回调模式端口（默认 {DEFAULT_CALLBACK_PORT}）")

    # token 子命令
    token_parser = subparsers.add_parser("token", help="授权码换取Token")
    token_parser.add_argument("--code", required=True, help="授权码")
    token_parser.add_argument("--state_token", required=True, help="状态标识")
    token_parser.add_argument("--config", default=DEFAULT_AUTH_CONFIG,
                              help="鉴权配置文件路径")
    token_parser.add_argument("--output", default=DEFAULT_AUTH_CACHE,
                              help="Token缓存文件路径")

    # check 子命令
    check_parser = subparsers.add_parser("check", help="检查Token有效性")
    check_parser.add_argument("--output", default=DEFAULT_AUTH_CACHE,
                               help="Token缓存文件路径")

    args = parser.parse_args()

    # Python 3.6 兼容：手动检查子命令
    if args.command is None:
        parser.error("请指定子命令: check, detect, login, token")

    # 分发到对应处理函数
    if args.command == "check":
        result_data = check_token(args.output)
    elif args.command == "detect":
        result_data = result("detect", "success", "环境检测完成",
                             detect_browser_environment())
    elif args.command == "login":
        # 根据 mode 确定登录方式
        force_mode = args.mode
        use_callback = (args.mode != "manual")  # 非 manual 模式都尝试回调

        result_data = login(
            config_path=args.config,
            output_path=args.output,
            force_mode=force_mode,
            use_callback=use_callback,
            callback_port=args.port
        )
    elif args.command == "token":
        # 解析配置文件路径
        resolved_config_path = _resolve_config_path(args.config)

        # 加载配置
        config_result = load_config_yaml(resolved_config_path)
        config = config_result.get("data", {})

        # 创建 AuthClient
        client = AuthClient()

        result_data = exchange_token(
            client, config["token_url"], args.code, args.state_token, args.output
        )

    print(json.dumps(result_data, indent=2, ensure_ascii=False))
    sys.exit(0 if result_data.get("success") else 1)


if __name__ == "__main__":
    main()