# -*- coding: utf-8 -*-
"""
OAuth2 本地回调服务器
启动临时 HTTP 服务器监听浏览器回调，接收授权码
"""

import base64
import hashlib
import secrets
import socket
import threading
import uuid
from typing import Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from utils.constants import (
    DEFAULT_CALLBACK_HOST,
    DEFAULT_CALLBACK_PORT,
    DEFAULT_CALLBACK_PATH,
    DEFAULT_CALLBACK_TIMEOUT,
)
from utils.errors import result


# ============================================================================
# PKCE 工具函数
# ============================================================================

def generate_pkce_pair() -> Tuple[str, str]:
    """
    生成 PKCE 的 verifier 和 challenge

    Returns:
        (verifier, challenge) 元组
    """
    # 生成 43-128 字符的随机 verifier
    verifier = secrets.token_urlsafe(96)[:128]

    # 计算 SHA256 的 challenge (S256 方法)
    challenge_bytes = hashlib.sha256(verifier.encode()).digest()
    # Base64 URL 安全编码，去掉 padding
    challenge = base64.urlsafe_b64encode(challenge_bytes).decode().rstrip("=")

    return verifier, challenge


def generate_state_token() -> str:
    """
    生成 state token (UUID 去掉连字符)

    Returns:
        32字符的 state token
    """
    return uuid.uuid4().hex


# ============================================================================
# 回调结果
# ============================================================================

class CallbackResult:
    """回调结果数据类"""

    def __init__(self, code: str, state: str):
        self.code = code
        self.state = state

    def __repr__(self) -> str:
        return f"CallbackResult(code='***', state='{self.state[:8]}...')"


# ============================================================================
# 本地回调服务器
# ============================================================================

class OAuthCallbackServer:
    """
    OAuth2 本地回调服务器

    启动临时 HTTP 服务器监听浏览器回调，接收授权码。
    只绑定到 127.0.0.1，不绑定 0.0.0.0。
    """

    def __init__(
        self,
        expected_state: str,
        host: str = DEFAULT_CALLBACK_HOST,
        port: int = 0,
        callback_path: str = DEFAULT_CALLBACK_PATH,
        timeout: int = DEFAULT_CALLBACK_TIMEOUT
    ):
        """
        初始化回调服务器

        Args:
            expected_state: 预期的 state 值（用于校验）
            host: 监听地址（默认 127.0.0.1）
            port: 监听端口（0 表示自动选择）
            callback_path: 回调路径（默认 /callback）
            timeout: 超时时间（秒）
        """
        self.expected_state = expected_state
        self.host = host
        self.port = port
        self.callback_path = callback_path
        self.timeout = timeout

        self._socket: Optional[socket.socket] = None
        self._actual_port: Optional[int] = None
        self._result: Optional[CallbackResult] = None
        self._error: Optional[str] = None
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def actual_port(self) -> int:
        """实际监听的端口"""
        return self._actual_port

    @property
    def redirect_uri(self) -> str:
        """回调 URI"""
        return f"http://{self.host}:{self._actual_port}{self.callback_path}"

    def start(self) -> Dict:
        """
        启动回调服务器

        Returns:
            result 字典，包含 redirect_uri
        """
        try:
            # 创建 socket
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._socket.bind((self.host, self.port))
            self._socket.listen(1)
            self._socket.settimeout(1.0)  # 用于定期检查 stop 事件

            self._actual_port = self._socket.getsockname()[1]

            # 启动监听线程
            self._thread = threading.Thread(target=self._listen, daemon=True)
            self._thread.start()

            return result(
                "callback_server",
                "started",
                f"回调服务器已启动: {self.redirect_uri}",
                data={"redirect_uri": self.redirect_uri, "port": self._actual_port},
                success=True
            )

        except OSError as e:
            return result(
                "callback_server",
                "error",
                f"启动回调服务器失败: {e}",
                success=False
            )

    def _listen(self):
        """监听连接"""
        while not self._stop_event.is_set():
            try:
                conn, addr = self._socket.accept()
                conn.settimeout(5.0)
                self._handle_connection(conn)
                if self._result or self._error:
                    break
            except socket.timeout:
                continue
            except OSError:
                break

    def _handle_connection(self, conn: socket.socket):
        """处理单个连接"""
        try:
            # 读取请求
            request = b""
            while b"\r\n\r\n" not in request:
                chunk = conn.recv(1024)
                if not chunk:
                    break
                request += chunk

            request_str = request.decode("utf-8", errors="ignore")

            # 解析请求行
            lines = request_str.split("\r\n")
            if not lines:
                self._send_response(conn, 400, "Bad Request")
                return

            request_line = lines[0]
            parts = request_line.split(" ")
            if len(parts) < 2:
                self._send_response(conn, 400, "Bad Request")
                return

            method, path = parts[0], parts[1]

            # 只处理 GET 请求
            if method != "GET":
                self._send_response(conn, 405, "Method Not Allowed")
                return

            # 解析路径
            parsed = urlparse(path)

            # 检查路径是否匹配
            if parsed.path != self.callback_path:
                self._send_response(conn, 404, "Not Found")
                return

            # 解析查询参数
            params = parse_qs(parsed.query)
            code = params.get("code", [None])[0]
            state = params.get("state", [None])[0]

            # 验证参数
            if not code:
                self._send_response(conn, 400, "Missing authorization code")
                return

            if not state:
                self._send_response(conn, 400, "Missing state parameter")
                return

            if state != self.expected_state:
                self._send_response(conn, 400, "State mismatch")
                self._error = "State mismatch"
                return

            # 成功
            self._result = CallbackResult(code=code, state=state)
            self._send_success_response(conn)

        except Exception as e:
            self._error = str(e)
            self._send_response(conn, 500, "Internal Server Error")
        finally:
            conn.close()

    def _send_response(self, conn: socket.socket, status: int, message: str):
        """发送文本响应"""
        body = f"{status} {message}".encode("utf-8")
        response = (
            f"HTTP/1.1 {status} {message}\r\n"
            f"Content-Type: text/plain; charset=utf-8\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        ).encode("utf-8") + body
        try:
            conn.sendall(response)
        except Exception:
            pass

    def _send_success_response(self, conn: socket.socket):
        """发送成功 HTML 响应"""
        html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <title>登录成功</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
            background: #f5f5f5;
        }
        .container {
            text-align: center;
            padding: 40px;
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        .icon {
            font-size: 48px;
            color: #4CAF50;
            margin-bottom: 20px;
        }
        h1 { color: #333; margin-bottom: 10px; }
        p { color: #666; }
    </style>
</head>
<body>
    <div class="container">
        <div class="icon">&#10003;</div>
        <h1>登录已回传到终端</h1>
        <p>浏览器已经成功把授权结果回调到本地监听器。</p>
        <p>你现在可以关闭这个页面，终端进程会继续完成 token 兑换。</p>
    </div>
</body>
</html>"""
        body = html.encode("utf-8")
        response = (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: text/html; charset=utf-8\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Cache-Control: no-store\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode("utf-8") + body
        try:
            conn.sendall(response)
        except Exception:
            pass

    def wait_for_callback(self) -> Dict:
        """
        等待浏览器回调

        Returns:
            result 字典，包含 code 和 state
        """
        if not self._thread:
            return result(
                "callback",
                "error",
                "回调服务器未启动",
                success=False
            )

        self._thread.join(timeout=self.timeout)

        if self._error:
            return result(
                "callback",
                "error",
                self._error,
                success=False
            )

        if self._result:
            return result(
                "callback",
                "success",
                "收到授权码",
                data={
                    "code": self._result.code,
                    "state": self._result.state
                }
            )

        return result(
            "callback",
            "timeout",
            f"等待回调超时 ({self.timeout}秒)",
            success=False
        )

    def stop(self):
        """停止回调服务器"""
        self._stop_event.set()
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)


# ============================================================================
# 便捷函数
# ============================================================================

def run_callback_server(
    expected_state: str,
    port: int = DEFAULT_CALLBACK_PORT,
    timeout: int = DEFAULT_CALLBACK_TIMEOUT
) -> Tuple[Optional[OAuthCallbackServer], Dict]:
    """
    启动回调服务器并返回服务器实例和启动结果

    Args:
        expected_state: 预期的 state 值
        port: 监听端口（0 表示自动选择）
        timeout: 超时时间

    Returns:
        (server, result) 元组
    """
    server = OAuthCallbackServer(
        expected_state=expected_state,
        port=port,
        timeout=timeout
    )
    start_result = server.start()
    return server, start_result