# -*- coding: utf-8 -*-
"""
流式文件读取模块

提供大文件的流式读取能力，使用生成器模式逐行处理，
避免一次性加载整个文件到内存。

函数:
    load_jsonl_stream: 流式读取 JSONL 文件
    load_csv_stream: 流式读取 CSV 文件
"""
import json
import csv
from pathlib import Path
from typing import Generator, Dict, Any

from utils.constants import ERR_FILE_NOT_FOUND, ERR_FILE_ENCODING, ERR_FILE_PARSE


# ============================================================================
# 内部迭代器类 - 用于支持 skipped_lines 属性
# ============================================================================

class _ErrorGenerator:
    """
    错误生成器 - 用于文件不存在等场景

    yield 一个错误对象后结束，支持 skipped_lines 属性
    """
    def __init__(self, code: int, message: str):
        self._code = code
        self._message = message
        self._yielded = False
        self.skipped_lines = 0

    def __iter__(self):
        return self

    def __next__(self):
        if self._yielded:
            raise StopIteration
        self._yielded = True
        return {
            "success": False,
            "message": self._message,
            "code": self._code
        }


class _JsonlStreamIterator:
    """
    JSONL 流式读取迭代器

    逐行读取 JSONL 文件，支持 skipped_lines 属性
    """
    def __init__(self, path: Path, encoding: str):
        self._path = path
        self._encoding = encoding
        self._file = None
        self._line_num = 0
        self.skipped_lines = 0
        self._encoding_error = False

    def __iter__(self):
        return self

    def __next__(self):
        # 编码错误已在第一次读取时检测
        if self._encoding_error:
            raise StopIteration

        # 延迟打开文件
        if self._file is None:
            try:
                self._file = open(self._path, 'r', encoding=self._encoding)
            except UnicodeDecodeError:
                self._encoding_error = True
                # 返回编码错误，下次迭代结束
                return {
                    "success": False,
                    "message": f"无法使用 {self._encoding} 编码读取文件: {self._path}",
                    "code": ERR_FILE_ENCODING
                }

        # 逐行读取
        while True:
            try:
                line = self._file.readline()
            except UnicodeDecodeError:
                # 编码错误可能在读取时发生
                self._encoding_error = True
                return {
                    "success": False,
                    "message": f"无法使用 {self._encoding} 编码读取文件: {self._path}",
                    "code": ERR_FILE_ENCODING
                }

            if not line:
                self._file.close()
                raise StopIteration

            self._line_num += 1
            stripped = line.strip()

            # 跳过空行（D-31）
            if not stripped:
                self.skipped_lines += 1
                continue

            # 解析 JSON
            try:
                data = json.loads(stripped)
                return {"data": data, "line": self._line_num}
            except json.JSONDecodeError as e:
                # D-29: yield 错误对象，不抛异常
                # D-33: 使用 ERR_FILE_PARSE (1003)
                return {
                    "success": False,
                    "line": self._line_num,
                    "message": f"JSON 解析失败: {e}",
                    "code": ERR_FILE_PARSE
                }


class _CsvStreamIterator:
    """
    CSV 流式读取迭代器

    逐行读取 CSV 文件，支持 skipped_lines 属性
    """
    def __init__(self, path: Path, encoding: str):
        self._path = path
        self._encoding = encoding
        self._file = None
        self._reader = None
        self.skipped_lines = 0
        self._encoding_error = False

    def __iter__(self):
        return self

    def __next__(self):
        # 编码错误已在初始化时检测
        if self._encoding_error:
            raise StopIteration

        # 延迟打开文件
        if self._file is None:
            try:
                self._file = open(self._path, 'r', encoding=self._encoding, newline='')
                self._reader = csv.DictReader(self._file)
            except UnicodeDecodeError:
                self._encoding_error = True
                return {
                    "success": False,
                    "message": f"无法使用 {self._encoding} 编码读取文件: {self._path}",
                    "code": ERR_FILE_ENCODING
                }

        # 逐行读取
        while True:
            try:
                row = next(self._reader)
            except StopIteration:
                self._file.close()
                raise
            except UnicodeDecodeError:
                # 编码错误可能在读取时发生
                self._encoding_error = True
                return {
                    "success": False,
                    "message": f"无法使用 {self._encoding} 编码读取文件: {self._path}",
                    "code": ERR_FILE_ENCODING
                }

            # CSV 行号：header=1，数据从 2 开始
            line_num = self._reader.line_num

            # 检查是否为空行（所有值为空或 None）
            if not row or all(v is None or v.strip() == '' for v in row.values() if v):
                self.skipped_lines += 1
                continue

            return {"data": dict(row), "line": line_num}


def load_jsonl_stream(path: str, encoding: str = "utf-8") -> Generator[Dict[str, Any], None, None]:
    """
    流式读取 JSONL 文件，逐行返回数据

    Args:
        path: 文件路径
        encoding: 文件编码（默认 utf-8）

    Yields:
        成功: {"data": <解析后的数据>, "line": <行号>}
        错误: {"success": False, "line": <行号>, "message": "<错误信息>", "code": <错误码>}

    属性:
        skipped_lines (int): 生成器耗尽后可访问，返回跳过的空行数

    Example:
        >>> gen = load_jsonl_stream("data.jsonl")
        >>> for item in gen:
        ...     if item.get("success") is False:
        ...         print(f"Error at line {item['line']}: {item['message']}")
        ...     else:
        ...         process(item["data"])
        >>> print(f"Skipped {gen.skipped_lines} empty lines")
    """
    p = Path(path)

    # 文件不存在 - 返回单元素错误生成器
    if not p.exists():
        return _ErrorGenerator(ERR_FILE_NOT_FOUND, f"文件不存在: {path}")

    # 使用迭代器包装器实现 skipped_lines 属性
    return _JsonlStreamIterator(p, encoding)


def load_csv_stream(path: str, encoding: str = "utf-8") -> Generator[Dict[str, Any], None, None]:
    """
    流式读取 CSV 文件，逐行返回数据

    Args:
        path: 文件路径
        encoding: 文件编码（默认 utf-8）

    Yields:
        {"data": <字典形式行数据>, "line": <行号>}

    属性:
        skipped_lines (int): 生成器耗尽后可访问，返回跳过的空行数

    Note:
        CSV 文件第一行为 header，数据行从 line=2 开始
    """
    p = Path(path)

    # 文件不存在 - 返回单元素错误生成器
    if not p.exists():
        return _ErrorGenerator(ERR_FILE_NOT_FOUND, f"文件不存在: {path}")

    # 使用迭代器包装器实现 skipped_lines 属性
    return _CsvStreamIterator(p, encoding)