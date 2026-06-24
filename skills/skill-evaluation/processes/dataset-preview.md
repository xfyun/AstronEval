---
name: dataset-preview
description: Use when dataset uploaded and need user to preview, delete or edit cases before submission
---

# 评测集预览与编辑流程

本流程定义如何在评测集就绪后让用户预览并按需删除/编辑。

---

## 触发条件

- 阶段3 任务2 步骤2 调用
- `eval-dataset.json` 与 `eval-dataset-meta.json` 已就绪

---

## 分支 A：直接提交（选项 1）

无需调整，直接结束本流程，进入阶段 4。

---

## 分支 B：删除用例（选项 2）

### 步骤B1：询问删除目标

直接让用户输入要删除的 `case_id`（支持多选，逗号分隔）。

> 请输入要删除的 case_id（多个用逗号分隔）：

### 步骤B2：执行云端删除

后台静默调用 `delete-cases` 命令（见 [脚本定义.md](../references/脚本定义.md#6-评测集管理)）。

### 步骤B3：同步本地

删除成功后，后台从本地 `eval-dataset.json` 中移除对应 case_id 的条目。

### 步骤B4：再次预览

回到阶段3 任务2 步骤1，重新展示用例摘要。

---

## 分支 C：编辑用例（选项 3）

### 步骤C1：告知用户

> 请直接修改本地 `eval-dataset.json`（路径：{local-path}）。修改完成后回复"已完成"。

### 步骤C2：等待用户确认

等待用户回复"已完成"或类似关键词。

### 步骤C3：覆盖云端

后台静默调用 `upload-dataset --dataset-id` 命令（见 [脚本定义.md](../references/脚本定义.md#6-评测集管理)），整份覆盖云端评测集。

### 步骤C4：再次预览

回到阶段3 任务2 步骤1，重新展示用例摘要。

---

## 一致性约束

任一操作完成后，本地 `eval-dataset.json` 与云端 `dataset-id` 对应的评测集必须保持一致。

| 操作 | 本地动作 | 云端动作 |
|------|----------|----------|
| 删除 | 从 `eval-dataset.json` 移除条目 | `delete-cases` 删除对应 case_id |
| 编辑 | 用户已修改 `eval-dataset.json` | `upload-dataset --dataset-id` 整份覆盖 |
| 直接提交 | 不变 | 不变 |

---

## 静默执行清单

下列动作必须全程静默：

- 调用 `delete-cases` 接口
- 调用 `upload-dataset --dataset-id` 接口
- 同步本地 `eval-dataset.json` 文件

仅在删除/编辑完成后向用户重新展示用例摘要。

---

## 输出

| 状态 | 说明 |
|------|------|
| 用户选项 1（直接提交） | 流程结束 |
| 用户选项 2（删除） | 删除完成后回到摘要展示，等待下一次选择 |
| 用户选项 3（编辑） | 编辑完成后回到摘要展示，等待下一次选择 |
