# -*- coding: utf-8 -*-
"""
文件处理模块

包含所有文件操作相关功能：
- load_json/save_json: JSON 文件读写
- load_config_yaml/load_config_kv: 配置文件加载
- load_data: 多格式数据文件加载
- load_jsonl_stream/load_csv_stream: 流式读取
- extract_fields/suggest_mapping: 字段映射工具
"""

from .file_utils import (
    load_json,
    save_json,
    load_config_yaml,
    load_config_kv,
    load_data,
    extract_fields,
    suggest_mapping,
)

from .streaming import (
    load_jsonl_stream,
    load_csv_stream,
)

__all__ = [
    'load_json',
    'save_json',
    'load_config_yaml',
    'load_config_kv',
    'load_data',
    'extract_fields',
    'suggest_mapping',
    'load_jsonl_stream',
    'load_csv_stream',
]