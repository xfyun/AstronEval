# -*- coding: utf-8 -*-
"""
客户端模块

包含所有与外部服务交互的客户端组件：
- BaseHttpClient: HTTP 基类
- AuthClient: 认证服务客户端
- ApiClient: 评测服务 API 客户端
- TokenManager: Token 管理
- OAuthCallbackServer: OAuth 回调服务器
"""

from .http_client import BaseHttpClient
from .auth_client import AuthClient
from .api_client import ApiClient
from .token_manager import TokenManager
from .oauth_callback import (
    generate_pkce_pair,
    generate_state_token,
    OAuthCallbackServer,
    run_callback_server,
)

__all__ = [
    'BaseHttpClient',
    'AuthClient',
    'ApiClient',
    'TokenManager',
    'generate_pkce_pair',
    'generate_state_token',
    'OAuthCallbackServer',
    'run_callback_server',
]