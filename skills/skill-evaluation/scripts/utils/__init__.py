# -*- coding: utf-8 -*-
"""
基础工具模块

包含通用基础设施：
- 常量定义
- 异常类和结果构建器
- 时间处理工具
"""

from .constants import (
    # 超时配置
    DEFAULT_TIMEOUT,
    DEFAULT_TOKEN_EXPIRY,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_POLL_TIMEOUT,
    # 重试配置
    MAX_RETRIES,
    RETRY_BACKOFF_FACTOR,
    # 错误码
    ERR_FILE_NOT_FOUND,
    ERR_FILE_ENCODING,
    ERR_FILE_PARSE,
    ERR_CONFIG_INVALID,
    ERR_NETWORK_TIMEOUT,
    ERR_NETWORK_CONNECTION,
    ERR_NETWORK_RETRY_EXHAUSTED,
    ERR_REMOTE_AUTH_EXPIRED,
    ERR_REMOTE_DEFAULT,
    # 默认路径
    DEFAULT_AUTH_CONFIG,
    DEFAULT_SERVER_CONFIG,
    DEFAULT_AUTH_CACHE,
    # OAuth 配置
    OOB_REDIRECT,
    DEFAULT_CALLBACK_HOST,
    DEFAULT_CALLBACK_PORT,
    DEFAULT_CALLBACK_PATH,
    DEFAULT_CALLBACK_TIMEOUT,
    # 状态
    TERMINAL_STATES,
    # 维度配置
    VALID_DIMENSION_TYPES,
    BUILTIN_FUNCTIONS,
    # 字段映射
    FIELD_PATTERNS,
    REQUIRED_FIELDS,
    OPTIONAL_FIELDS,
)

from .errors import (
    result,
    ResultDict,
    handle_cli_error,
    EvalError,
    FileEncodingError,
    FileParseError,
    FileNotFoundError,
    ConfigError,
    NetworkError,
    NetworkTimeoutError,
    NetworkConnectionError,
    AuthExpiredError,
    ApiError,
)

from .datetime_utils import (
    parse_iso_datetime,
    is_expired,
)

from .keypoint_prompts import (
    SYSTEM_PROMPT,
    build_user_prompt,
)

__all__ = [
    # 常量
    'DEFAULT_TIMEOUT',
    'DEFAULT_TOKEN_EXPIRY',
    'DEFAULT_POLL_INTERVAL',
    'DEFAULT_POLL_TIMEOUT',
    'MAX_RETRIES',
    'RETRY_BACKOFF_FACTOR',
    'ERR_FILE_NOT_FOUND',
    'ERR_FILE_ENCODING',
    'ERR_FILE_PARSE',
    'ERR_CONFIG_INVALID',
    'ERR_NETWORK_TIMEOUT',
    'ERR_NETWORK_CONNECTION',
    'ERR_NETWORK_RETRY_EXHAUSTED',
    'ERR_REMOTE_AUTH_EXPIRED',
    'ERR_REMOTE_DEFAULT',
    'DEFAULT_AUTH_CONFIG',
    'DEFAULT_SERVER_CONFIG',
    'DEFAULT_AUTH_CACHE',
    'OOB_REDIRECT',
    'DEFAULT_CALLBACK_HOST',
    'DEFAULT_CALLBACK_PORT',
    'DEFAULT_CALLBACK_PATH',
    'DEFAULT_CALLBACK_TIMEOUT',
    'TERMINAL_STATES',
    'VALID_DIMENSION_TYPES',
    'BUILTIN_FUNCTIONS',
    'FIELD_PATTERNS',
    'REQUIRED_FIELDS',
    'OPTIONAL_FIELDS',
    # 错误处理
    'result',
    'ResultDict',
    'handle_cli_error',
    'EvalError',
    'FileEncodingError',
    'FileParseError',
    'FileNotFoundError',
    'ConfigError',
    'NetworkError',
    'NetworkTimeoutError',
    'NetworkConnectionError',
    'AuthExpiredError',
    'ApiError',
    # 时间处理
    'parse_iso_datetime',
    'is_expired',
    # 评测点生成
    'SYSTEM_PROMPT',
    'build_user_prompt',
]