# -*- coding: utf-8 -*-
"""
文件工具函数模块
统一 JSON/YAML/配置文件的读写操作
"""
import json
import csv
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from utils.constants import (
    ERR_FILE_NOT_FOUND,
    ERR_FILE_ENCODING,
    ERR_FILE_PARSE,
    ERR_CONFIG_INVALID,
    REQUIRED_FIELDS,
    OPTIONAL_FIELDS,
    FIELD_PATTERNS,
    CASE_ID_EXACT_MATCH,
)
from utils.errors import (
    result,
    FileEncodingError,
    FileParseError,
    ConfigError,
)


# ============================================================================
# JSON 文件操作
# ============================================================================

def load_json(path: str, encoding: str = "utf-8") -> Dict[str, Any]:
    """
    加载 JSON 文件

    Args:
        path: 文件路径
        encoding: 文件编码（默认 utf-8）

    Returns:
        成功: {"success": True, "data": {...}, ...}
        失败: {"success": False, "code": ..., "message": ...}

    注意: D-03 - 文件不存在或无效时返回错误字典，而非 None
    """
    p = Path(path)

    if not p.exists():
        return result("load", "not_found", f"文件不存在: {path}", code=ERR_FILE_NOT_FOUND)

    try:
        content = p.read_text(encoding=encoding)
        data = json.loads(content)
        return result("load", "loaded", f"成功加载: {path}", data=data)
    except UnicodeDecodeError:
        return result("load", "encoding_error",
                     f"无法使用 {encoding} 编码读取文件: {path}",
                     code=ERR_FILE_ENCODING)
    except json.JSONDecodeError as e:
        return result("load", "parse_error",
                     f"JSON 解析失败: {path} - {e}",
                     code=ERR_FILE_PARSE)


def save_json(path: str, data: Any, encoding: str = "utf-8") -> Dict[str, Any]:
    """
    保存数据到 JSON 文件

    Args:
        path: 文件路径
        data: 要保存的数据
        encoding: 文件编码（默认 utf-8）

    Returns:
        {"success": True, "message": "保存成功", "path": ...}
    """
    p = Path(path)

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(data, indent=2, ensure_ascii=False)
        p.write_text(content, encoding=encoding)
        return result("save", "saved", f"保存成功: {path}", data={"path": str(p)})
    except Exception as e:
        return result("save", "error", f"保存失败: {e}", success=False)


# ============================================================================
# 配置文件操作
# ============================================================================

def _parse_simple_yaml(content: str) -> Dict[str, Any]:
    """
    简单 YAML 解析器（仅支持 key: value 格式）

    用于解析项目配置文件，避免依赖 pyyaml 库。
    支持格式：
    - key: value
    - key: "quoted value"
    - key: 'quoted value'
    - # 注释行
    - 空行
    """
    data = {}

    for line in content.split('\n'):
        line = line.strip()

        # 跳过空行和注释
        if not line or line.startswith('#'):
            continue

        # 解析 key: value
        if ':' in line:
            key, value = line.split(':', 1)
            key = key.strip()
            value = value.strip()

            # 解析值类型
            if not value:
                data[key] = None
            elif value.startswith('"') and value.endswith('"'):
                data[key] = value[1:-1]
            elif value.startswith("'") and value.endswith("'"):
                data[key] = value[1:-1]
            elif value.lower() == 'true':
                data[key] = True
            elif value.lower() == 'false':
                data[key] = False
            elif value.lower() == 'null':
                data[key] = None
            else:
                # 尝试数字，否则作为字符串
                try:
                    if '.' in value:
                        data[key] = float(value)
                    else:
                        data[key] = int(value)
                except ValueError:
                    data[key] = value

    return data


def load_config_yaml(path: str, encoding: str = "utf-8") -> Dict[str, Any]:
    """
    加载 YAML 配置文件

    用于加载 YAML 格式的配置文件（如 eval-auth.cfg 可能是 YAML）。
    使用内置解析器，无需 pyyaml 依赖。
    """
    p = Path(path)

    if not p.exists():
        return result("load_config", "not_found", f"配置文件不存在: {path}",
                     code=ERR_FILE_NOT_FOUND)

    try:
        content = p.read_text(encoding=encoding)
        data = _parse_simple_yaml(content)
        if data is None:
            data = {}
        return result("load_config", "loaded", f"配置加载成功: {path}", data=data)
    except Exception as e:
        return result("load_config", "parse_error", f"配置解析失败: {e}",
                     code=ERR_CONFIG_INVALID)
    except UnicodeDecodeError:
        return result("load_config", "encoding_error",
                     f"无法使用 {encoding} 编码读取文件: {path}",
                     code=ERR_FILE_ENCODING)


def load_config_kv(path: str, encoding: str = "utf-8") -> Dict[str, Any]:
    """
    加载 key:value 格式的配置文件

    用于加载服务配置文件（如 eval-server.cfg）。
    格式为每行一个 key: value 对。
    """
    p = Path(path)

    if not p.exists():
        return result("load_config", "not_found", f"配置文件不存在: {path}",
                     code=ERR_FILE_NOT_FOUND)

    try:
        config = {}
        for line in p.read_text(encoding=encoding).splitlines():
            if ':' in line:
                key, value = line.split(':', 1)
                config[key.strip()] = value.strip().strip('"')

        return result("load_config", "loaded", f"配置加载成功: {path}", data=config)
    except UnicodeDecodeError:
        return result("load_config", "encoding_error",
                     f"无法使用 {encoding} 编码读取文件: {path}",
                     code=ERR_FILE_ENCODING)


# ============================================================================
# 数据文件操作
# ============================================================================

def load_data(path: str, encoding: str = "utf-8") -> Dict[str, Any]:
    """
    根据文件类型加载数据

    支持: .json, .jsonl, .csv, .xlsx, .xls

    Returns:
        {"success": True, "data": [...], "format": "jsonl", ...}
    """
    p = Path(path)

    if not p.exists():
        return result("load_data", "not_found", f"数据文件不存在: {path}",
                     code=ERR_FILE_NOT_FOUND)

    suffix = p.suffix.lower()

    try:
        if suffix == '.jsonl':
            lines = p.read_text(encoding=encoding).splitlines()
            data = [json.loads(line) for line in lines if line.strip()]
            return result("load_data", "loaded", f"成功加载 {len(data)} 条记录",
                        data={"items": data, "format": "jsonl", "total": len(data)})

        if suffix == '.json':
            content = p.read_text(encoding=encoding)
            data = json.loads(content)
            if not isinstance(data, list):
                data = [data]
            return result("load_data", "loaded", f"成功加载 {len(data)} 条记录",
                        data={"items": data, "format": "json", "total": len(data)})

        if suffix == '.csv':
            import csv
            with open(path, 'r', encoding=encoding) as f:
                reader = csv.DictReader(f)
                data = list(reader)
            return result("load_data", "loaded", f"成功加载 {len(data)} 条记录",
                        data={"items": data, "format": "csv", "total": len(data)})

        if suffix in ('.xlsx', '.xls'):
            try:
                import pandas as pd
                data = pd.read_excel(path).to_dict('records')
                return result("load_data", "loaded", f"成功加载 {len(data)} 条记录",
                            data={"items": data, "format": "xlsx", "total": len(data)})
            except ImportError:
                return result("load_data", "error", "处理 Excel 文件需要安装 pandas",
                             success=False)

        return result("load_data", "error", f"不支持的文件格式: {suffix}", success=False)

    except json.JSONDecodeError as e:
        return result("load_data", "parse_error", f"JSON 解析失败: {e}",
                     code=ERR_FILE_PARSE)
    except UnicodeDecodeError:
        return result("load_data", "encoding_error",
                     f"无法使用 {encoding} 编码读取文件: {path}",
                     code=ERR_FILE_ENCODING)


# ============================================================================
# 字段映射工具
# ============================================================================

def extract_fields(items: List[dict]) -> Dict[str, Any]:
    """
    从数据项提取字段信息
    """
    fields = {}
    for item in items[:100]:
        if not isinstance(item, dict):
            continue
        for key, value in item.items():
            if key not in fields:
                fields[key] = {"type": type(value).__name__}
    return fields


def suggest_mapping(fields: Dict) -> Dict[str, Dict]:
    """
    根据字段名建议映射

    返回格式：
    {
        "question": {"source_field": "question", "default": null},
        "answer": {"source_field": "answer", "default": null},
        "model": {"source_field": null, "default": null},
        "case_id": {"source_field": "id", "default": null}
    }

    匹配规则：
    1. 精确匹配优先（字段名完全等于关键词）
    2. 包含匹配次之（字段名包含关键词，按关键词长度降序优先）

    特殊处理：
    - 'id' 字段精确匹配到 case_id（避免 seq_id、user_id 误匹配）
    """
    mapping = {}
    for field_name in fields:
        field_lower = field_name.lower()

        # 特殊处理：'id' 精确匹配到 case_id
        if field_lower in CASE_ID_EXACT_MATCH and 'case_id' not in mapping:
            mapping['case_id'] = {"source_field": field_name, "default": None}
            continue

        for target, keywords in FIELD_PATTERNS.items():
            if target in mapping:
                continue
            # 1. 精确匹配
            if field_lower in keywords:
                mapping[target] = {"source_field": field_name, "default": None}
                break
            # 2. 包含匹配，按关键词长度降序优先匹配更精确的关键词
            sorted_keywords = sorted([k for k in keywords if len(k) >= 3], key=len, reverse=True)
            if any(k in field_lower for k in sorted_keywords):
                mapping[target] = {"source_field": field_name, "default": None}
                break

    # 确保必填字段都有映射条目（即使 source_field 为 null）
    for field in REQUIRED_FIELDS:
        if field not in mapping:
            mapping[field] = {"source_field": None, "default": None}

    return mapping