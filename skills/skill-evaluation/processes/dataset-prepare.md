---
name: dataset-prepare
description: Use when in dataset phase and need to validate, convert, upload custom Excel or auto-generate dataset
---

# 评测集准备流程

本流程定义如何完成评测集的获取——自定义 Excel 上传或平台自动合成。

---

## 触发条件

- 阶段3 任务1 步骤2 调用
- 用户已选择评测集来源

---

## 分支 A：自定义 Excel 上传

### 步骤A1：告知模板并请求路径

**必须打印**——在请求 Excel 路径的同一轮输出中，**一并展示**字段说明与示例：

> Excel 文件需包含以下字段：
>
> | 字段 | 是否必填 | 说明 |
> |------|----------|------|
> | `question` | **必填** | 评测问题 |
> | `case_id` | 否 | 用例唯一标识（不填则自动生成） |
> | `category` | 否 | 问题分类 |
> | `keypoint` | 否 | 评测要点，JSON 数组格式，如 `["要点1", "要点2"]` |
> | `filelist` | 否 | 关联附件的绝对文件路径，多个路径以逗号分隔 |
>
> 示例：
>
> | case_id | question | category | keypoint | filelist |
> |---------|----------|----------|----------|---------|
> | case_0001 | 请根据以下需求生成完整的测试方案：项目名称：在线教育平台-课程购买模块... | 方案生成 | ["是否包含测试需求列表且覆盖所有功能点", "是否包含质量目标章节"] | |
> | case_0002 | 请根据附件中的需求文档，生成测试方案并重点制定性能测试策略 | 策略规划 | ["是否包含性能测试策略矩阵表", "是否识别出性能测试相关风险项"] | /path/to/需求文档.pdf |
>
> 请提供评测集 Excel 文件路径。

### 步骤A2：执行验证、转换、上传

后台**全程静默**执行：

1. `convert-excel`：验证并转换 Excel → `eval-dataset.json`

```bash
{python-cmd} "{skill-dir}/scripts/eval_skill.py" convert-excel \
  --file "{excel-path}" \
  --output "{work-dir}/.eval/{session-id}/eval-dataset.json" \
  --config "{skill-dir}/scripts/cfg/eval-server.cfg"
```

2. `upload-dataset`：上传到云端，写入 `eval-dataset-meta.json`（含 `dataset-id`）

```bash
{python-cmd} "{skill-dir}/scripts/eval_skill.py" upload-dataset \
  --config "{skill-dir}/scripts/cfg/eval-server.cfg" \
  --dataset "{work-dir}/.eval/{session-id}/eval-dataset.json" \
  --output "{work-dir}/.eval/{session-id}/eval-dataset-meta.json"
```

**禁止**输出"正在验证"、"正在转换"、"正在上传"等中间提示。

### 步骤A3：检查字段完整性

后台静默执行 `check-dataset` 命令检查字段完整性：

```bash
{python-cmd} "{skill-dir}/scripts/eval_skill.py" check-dataset \
  --dataset "{work-dir}/.eval/{session-id}/eval-dataset.json"
```

| `needs_completion` | 后续动作 |
|---------------------|----------|
| `false` | 进入步骤A4 |
| `true` | 进入步骤A5（自动补全） |

### 步骤A4：完成提示（无需补全）

向用户输出：

> 评测集已就绪，共 {n} 条用例，已保存至 {local-path}

不打印 `dataset-id`。

### 步骤A5：自动补全字段

后台静默执行，补全缺少的 `category` 和 `keypoint` 字段：

1. `datamaker`：提交合成任务，写入 `eval-datamaker.json`

```bash
{python-cmd} "{skill-dir}/scripts/eval_skill.py" datamaker \
  --config "{skill-dir}/scripts/cfg/eval-server.cfg" \
  --skill-names {skill-name-1},{skill-name-2} \
  --skill-urls {skill-zip-url-1},{skill-zip-url-2} \
  --dataset-id {dataset-id} \
  --output "{work-dir}/.eval/{session-id}/eval-datamaker.json"
```

2. `datamaker-status`：轮询合成结果（间隔 30 秒，超时 1 小时），写入 `eval-datamaker-result.json`

```bash
{python-cmd} "{skill-dir}/scripts/eval_skill.py" datamaker-status \
  --config "{skill-dir}/scripts/cfg/eval-server.cfg" \
  --id {datamaker-id} \
  --output "{work-dir}/.eval/{session-id}/eval-datamaker-result.json" \
  --poll --interval 30 --timeout 3600
```

3. `list-dataset`（`--all`）：下载补全后的完整样例到本地 `eval-dataset.json`

**禁止**输出任何中间提示，包括"正在补全"、"正在合成"等。

### 步骤A6：完成提示（已补全）

向用户输出：

> 评测集已就绪（自动补全），共 {n} 条用例，已保存至 {local-path}

不打印 `dataset-id`，不提示已执行补全操作。

---

## 分支 B：平台自动合成

### 步骤B1：提交合成任务

后台静默执行：

1. `datamaker`：提交合成任务，写入 `eval-datamaker.json`

```bash
{python-cmd} "{skill-dir}/scripts/eval_skill.py" datamaker \
  --config "{skill-dir}/scripts/cfg/eval-server.cfg" \
  --skill-names {skill-name-1},{skill-name-2} \
  --skill-urls {skill-zip-url-1},{skill-zip-url-2} \
  --output "{work-dir}/.eval/{session-id}/eval-datamaker.json"
```

2. `datamaker-status`：轮询合成结果（间隔 30 秒，超时 1 小时），写入 `eval-datamaker-result.json`

```bash
{python-cmd} "{skill-dir}/scripts/eval_skill.py" datamaker-status \
  --config "{skill-dir}/scripts/cfg/eval-server.cfg" \
  --id {datamaker-id} \
  --output "{work-dir}/.eval/{session-id}/eval-datamaker-result.json" \
  --poll --interval 30 --timeout 3600
```

**禁止**输出任何中间提示，包括"正在提交"、"正在合成"、"正在轮询"、"将从云端下载"、"合成需要几分钟"、"请稍候"等。

### 步骤B2：下载样例到本地

合成完成后，后台静默调用 `list-dataset`（`--all`）下载完整样例到本地 `eval-dataset.json`。

### 步骤B3：完成提示

向用户输出：

> 评测集已就绪，共 {n} 条用例，已保存至 {local-path}

不打印 `dataset-id`。

---

## 失败处理

| 失败场景 | 处理 |
|----------|------|
| Excel 缺少必填 `question` 字段 | 提示用户参考模板补充 `question` 列后重新提供 |
| Excel 路径不存在 | 提示用户检查路径并重新提供 |
| 合成超时（> 1 小时） | 提示用户稍后用历史任务恢复，或改用自定义上传 |
| 合成任务返回 Failed | 展示错误信息（从 `eval-datamaker-result.json` 提取） |

---

## 输出

| 文件 | 内容 |
|------|------|
| `{work-dir}/.eval/{session-id}/eval-dataset.json` | 评测集内容 |
| `{work-dir}/.eval/{session-id}/eval-dataset-meta.json` | 评测集元信息（含 `dataset-id`） |

| 变量 | 说明 |
|------|------|
| `{dataset-id}` | 评测集 ID（内部使用，不展示给用户） |
| `{n}` | 用例总数 |
| `{local-path}` | `eval-dataset.json` 的绝对路径 |
