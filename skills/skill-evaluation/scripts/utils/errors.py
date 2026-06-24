# -*- coding: utf-8 -*-
"""
自定义异常类和错误处理工具
"""
import sys
import json
from typing import Dict, Any, TypedDict, Optional
from .constants import (
    ERR_FILE_NOT_FOUND,
    ERR_FILE_ENCODING,
    ERR_FILE_PARSE,
    ERR_CONFIG_INVALID,
    ERR_NETWORK_TIMEOUT,
    ERR_NETWORK_CONNECTION,
    ERR_REMOTE_AUTH_EXPIRED,
    ERR_REMOTE_DEFAULT,
)


# ============================================================================
# 类型定义
# ============================================================================

class _ResultDictRequired(TypedDict):
    """统一返回结果类型 - 必填字段"""
    success: bool
    action: str
    status: str
    message: str


class ResultDict(_ResultDictRequired, total=False):
    """统一返回结果类型 - 可选字段"""
    data: Dict[str, Any]
    code: int


# ============================================================================
# 结果构建器
# ============================================================================

def result(action: str, status: str, message: str,
           data: Optional[Dict[str, Any]] = None,
           success: Optional[bool] = None,
           code: Optional[int] = None) -> ResultDict:
    """
    统一构建返回结果

    Args:
        action: 操作类型（如 "check", "load", "save"）
        status: 状态描述（如 "valid", "error", "not_found"）
        message: 详细消息
        data: 附加数据
        success: 是否成功（None 时根据 status 自动判断）
        code: 错误码（可选）

    Returns:
        标准化的结果字典
    """
    if success is None:
        success = status in ("valid", "success", "waiting", "loaded", "saved")

    r = {
        "success": success,
        "action": action,
        "status": status,
        "message": message,
        "data": data or {}
    }
    if code is not None:
        r["code"] = code
    return r


# ============================================================================
# 自定义异常基类
# ============================================================================

class EvalError(Exception):
    """
    评测错误基类

    所有脚本本地错误的基类，包含错误码和消息。
    """
    def __init__(self, message: str, code: int = None):
        self.message = message
        self.code = code
        super().__init__(message)

    def to_dict(self) -> Dict[str, Any]:
        """转换为错误字典"""
        return {
            "success": False,
            "code": self.code,
            "message": self.message
        }


# ============================================================================
# 文件相关异常
# ============================================================================

class FileEncodingError(EvalError):
    """
    文件编码错误

    当无法使用指定编码读取文件时抛出。
    """
    def __init__(self, path: str, encoding: str = "utf-8"):
        self.path = path
        self.encoding = encoding
        super().__init__(
            f"无法使用 {encoding} 编码读取文件: {path}",
            code=ERR_FILE_ENCODING
        )


class FileParseError(EvalError):
    """
    文件解析错误

    当文件内容无法解析（如 JSON 格式错误）时抛出。
    """
    def __init__(self, path: str, detail: str = ""):
        self.path = path
        self.detail = detail
        msg = f"文件解析失败: {path}"
        if detail:
            msg += f" - {detail}"
        super().__init__(msg, code=ERR_FILE_PARSE)


class FileNotFoundError(EvalError):
    """
    文件不存在错误
    """
    def __init__(self, path: str):
        self.path = path
        super().__init__(f"文件不存在: {path}", code=ERR_FILE_NOT_FOUND)


# ============================================================================
# 配置相关异常
# ============================================================================

class ConfigError(EvalError):
    """
    配置错误
    """
    def __init__(self, message: str, path: str = None):
        self.path = path
        msg = message
        if path:
            msg = f"{message} (文件: {path})"
        super().__init__(msg, code=ERR_CONFIG_INVALID)


# ============================================================================
# 网络相关异常
# ============================================================================

class NetworkError(EvalError):
    """
    网络错误

    用于网络请求失败的情况，包含原始异常引用。
    """
    def __init__(self, message: str, original_error: Exception = None,
                 code: int = ERR_NETWORK_TIMEOUT):
        self.original_error = original_error
        super().__init__(message, code=code)


class NetworkTimeoutError(NetworkError):
    """
    网络超时错误
    """
    def __init__(self, message: str = "请求超时", original_error: Exception = None):
        super().__init__(message, original_error, code=ERR_NETWORK_TIMEOUT)


class NetworkConnectionError(NetworkError):
    """
    网络连接错误
    """
    def __init__(self, message: str = "连接失败", original_error: Exception = None):
        super().__init__(message, original_error, code=ERR_NETWORK_CONNECTION)


# ============================================================================
# 认证相关异常
# ============================================================================

class AuthExpiredError(EvalError):
    """
    Token 过期错误

    远程服务错误码透传（10002）。
    """
    def __init__(self, message: str = "Token 已过期，请重新授权"):
        # 使用远程服务错误码（透传）
        super().__init__(message, code=ERR_REMOTE_AUTH_EXPIRED)


class ApiError(EvalError):
    """
    API 错误 - 透传远程错误码

    D-10: 透传远程服务错误，保留原 code 和 message
    """
    def __init__(self, message: str, code: int = None, data: dict = None):
        self.data = data or {}
        super().__init__(message, code=code)


# ============================================================================
# CLI 错误处理
# ============================================================================

def handle_cli_error(e: Exception) -> None:
    """
    统一的 CLI 错误处理，打印错误信息并退出

    处理策略：
    - EvalError 及其子类：使用异常自身的 code 和 message
    - 其他异常：使用默认错误码 ERR_REMOTE_DEFAULT

    输出格式：{"success": False, "code": int, "message": str}
    """
    if isinstance(e, EvalError):
        # 所有 EvalError 子类都有 code 和 message 属性
        print(json.dumps({
            "success": False,
            "code": e.code,
            "message": e.message
        }, ensure_ascii=False))
    else:
        # 非自定义异常（如 requests 库的异常、ValueError 等）
        print(json.dumps({
            "success": False,
            "code": ERR_REMOTE_DEFAULT,
            "message": str(e)
        }, ensure_ascii=False))
    sys.exit(1)