---
name: eval-build
description: Use when initialization completed and ready to configure evaluation targets (skill, runtime, driver model, judge model)
---

# 配置评测对象阶段

## 目标

完成 Skill 选择、运行框架选择、驱动模型选择、评委模型选择，输出已上传的 Skill zip URL 列表与模型配置文件。

核心原则：**用户视角隐藏实现，关键确认不可跳过**。

**术语约束**（本阶段涉及模型选择，以下内部术语禁止向用户暴露）：

| 用户可见 | 禁止暴露 |
|----------|----------|
| 云端模型、自定义模型 | `TokenPlan`、`EvalPlan`、`limited_free` |
| 驱动模型、评委模型 | `candidate`、`judge`、`usage`、`source` |

**前置验证**：Token 有效；评测场景已确认。验证失败则返回初始化阶段。

---

## 何时使用

- 初始化阶段已完成（鉴权、场景识别就绪）
- 需要选择待评测 Skill 与模型时

---

## 阶段完成标志

| 验证条件 | 不满足时执行 |
|----------|--------------|
| 已生成会话目录 `{work-dir}/.eval/{session-id}/` | 任务1 |
| 至少 1 个 Skill zip URL 已就绪 | 任务1 |
| `eval-runtimes.json` 存在（运行框架配置） | 任务2 |
| `eval-models.json` 存在（驱动模型列表） | 任务3 |
| `eval-judge.json` 存在（评委配置） | 任务4 |

全部通过后进入数据准备阶段（加载 [eval-set.md](./eval-set.md)）。

---

## 流程速查

| 流程 | 文档位置 | 调用时机 |
|------|----------|----------|
| Skill 选择与上传 | [skill-selection.md](./processes/skill-selection.md) | 任务1 |
| 模型选择 | [model-selection.md](./processes/model-selection.md) | 任务2、任务3 |

---

## 任务列表

### 任务1：选择 Skill

**用户视角**：按名称搜索或直接给地址，得到一个或多个待评测 Skill。

**输出**：每个 Skill 对应一个 `{skill-zip-url}`；会话目录已创建。

#### Skill 数量决策

根据初始化阶段确定的评测场景：

| 评测场景 | Skill 数量 |
|---------|-----------|
| 快速效果验证、驱动模型横评 | 1 个 |
| 同类 Skill 横评、Skill 版本对比、A/B Test | 多个 |

#### 步骤1：选择获取方式

**自动填充检查**：若上下文已识别出 Skill 名称或路径，跳过本次询问，直接以下规则进入步骤2 的对应分支：

| 上下文已知信息 | 进入的分支 |
|---------------|----------|
| Skill 名称（如 `my-skill`） | 步骤2 → [skill-selection.md 分支 A：按名称搜索](./processes/skill-selection.md#分支-a按名称搜索) |
| Skill 路径（本地目录 / .zip / https:// URL） | 步骤2 → [skill-selection.md 分支 B：提供 Skill 地址](./processes/skill-selection.md#分支-b提供-skill-地址) |

否则向用户展示：

> 请选择获取 Skill 的方式：
>
> | 选项 | 方式 | 说明 |
> |:----:|------|------|
> | 1 | 按名称搜索 | 本地与云端（ClawHub）一起搜索，命中后由你选择 |
> | 2 | 提供 Skill 地址 | 直接给出本地 Skill 路径或云端 zip URL |

#### 步骤2：执行 Skill 选择子流程

执行 [skill-selection.md](./processes/skill-selection.md) 流程，完成搜索/识别/打包/上传。

**用户可见的展示**：仅"找到的 Skill 候选项"（含来源与位置），以及"是否一并打包依赖"询问（如适用）。其余打包、上传步骤静默完成。

需要多个评测对象时，对每个对象分别完成"选择获取方式 → 取到 zip → 上传"。

---

### 任务2：选择运行框架

**用户视角**：选择运行 Skill 的框架环境；横评场景多选。

**输出**：`{work-dir}/.eval/{session-id}/eval-runtimes.json`

#### 运行框架数量决策

| 评测场景 | 运行框架数量 |
|---------|------------|
| 快速效果验证、同类 Skill 横评、驱动模型横评、Skill 版本对比 | 1 个 |
| 运行框架横评 | 多个（≥2） |

#### 步骤1：展示运行框架选项

**自动填充检查**：若上下文已指定运行框架（如用户说"用 openclaw 跑 xxx Skill"），跳过询问，直接使用指定框架。

向用户展示：

> **可选运行框架：**
>
> | 序号 | 框架 |
> |:----:|------|
> | 1 | Claude Code |
> | 2 | OpenClaw |
> | 3 | Hermes |

询问语句根据评测场景决定的运行框架数量：

| 评测场景 | 需选择数量 | 询问语句 |
|---------|-----------|---------|
| 快速效果验证、同类 Skill 横评、驱动模型横评、Skill 版本对比 | 1 个 | `请选择运行框架（输入序号）：` |
| 运行框架横评 | ≥2 个（多选） | `请选择运行框架（输入序号，可多选，逗号分隔，至少 2 个）：` |

#### 步骤2：回显结果

用户选择后回显框架名称：

> 已选运行框架：Claude Code、OpenClaw

#### 步骤3：生成运行框架配置文件

后台静默调用 `build-runtimes` 命令，生成 `eval-runtimes.json`：

```bash
{python-cmd} "{skill-dir}/scripts/eval_skill.py" build-runtimes \
  --output-dir "{work-dir}/.eval/{session-id}" \
  --runtimes {runtime-type-1},{runtime-type-2}
```

> ⚠️ **参数格式**：`--runtimes` 参数值必须使用小写格式：`claude-code`、`openclaw`、`hermes`（与展示格式 `Claude Code` 不同）。

此步骤完成后，`eval-runtimes.json` 已就绪。

---

### 任务3：选择驱动模型

**用户视角**：直接展示可选模型列表（云端模型 + 自定义选项），用户从中选择；横评场景多选。

**输出**：`{work-dir}/.eval/{session-id}/eval-models.json`

#### 驱动模型数量决策

| 评测场景 | 驱动模型数量 |
|---------|-------------|
| 快速效果验证、同类 Skill 横评、Skill 版本对比、运行框架横评 | 1 个 |
| 驱动模型横评 | 多个 |

#### 步骤1：执行模型选择子流程

**自动填充检查**：若上下文已指定驱动模型名称，跳过询问，直接在模型列表中匹配。

执行 [model-selection.md](./processes/model-selection.md) 流程：

1. **拉取云端模型**：调用 `models --usage candidate` 获取
2. **读取历史自定义模型**：从 `custom-models.json`（按 `usage=candidate` 过滤）获取
3. **按名称排序**：云端模型按 `display_name` 字母顺序排序
4. **展示列表**：排序后的云端模型 + "自定义模型"选项

#### 步骤2：回显结果

用户选择后仅回显模型显示名称：

> 已选驱动模型：GLM-5、DeepSeek-V3

---

### 任务4：选择评委模型

**用户视角**：平台先推荐一个评委模型，用户确认或重新选择；单选。

**输出**：`{work-dir}/.eval/{session-id}/eval-judge.json`

#### 步骤1：执行模型选择子流程

后台静默拉取评委模型列表（`--usage judge`），执行 [model-selection.md](./processes/model-selection.md) 流程：

1. **明确已选驱动模型**：读取用户在任务3中选择的驱动模型名称列表
2. **按名称排序**：评委候选列表按 `display_name` 字母顺序排序
3. **排除已选驱动模型**：从排序后的列表中排除已选驱动模型（按 `display_name` 精确匹配）
4. **取第一个作为推荐**：排除后的列表第一个作为推荐评委
5. **展示推荐并询问确认**

向用户展示：

> **推荐评委模型**：{推荐模型 display_name}
>
> 是否使用该评委模型？
>
> | 选项 | 说明 |
> |:----:|------|
> | 1 | 确认使用 |
> | 2 | 选择其他模型 |

| 用户选择 | 后续动作 |
|----------|----------|
| 1 - 确认使用 | 直接选中该模型，进入步骤2 |
| 2 - 选择其他 | 展示完整评委模型列表（同样排除已选驱动模型，最后一行为"自定义模型"选项）|

#### 步骤2：重叠提示

**判断规则**：仅当驱动模型的**名称**与评委模型的**名称**完全相同（精确匹配，非包含匹配）时，才认为有重叠。例如 `GLM-5` 与 `GLM-5.1` 是不同模型，不触发重叠提示。

若评委模型与驱动模型有重叠，提示：

> ⚠️ 驱动模型中包含评委模型「{judge-display-name}」，评委对自身输出评分可能存在自我偏好偏差，影响客观性。

#### 步骤3：生成模型配置文件

后台静默调用 `build-models` 命令，生成 `eval-models.json` 与 `eval-judge.json`：

```bash
{python-cmd} "{skill-dir}/scripts/eval_skill.py" build-models \
  --output-dir "{work-dir}/.eval/{session-id}" \
  --judge-json '{judge-model-object-json}' \
  --models-json '{driver-models-array-json}' \
  --work-dir "{work-dir}" \
  --session-id "{session-id}"
```

此步骤完成后，`eval-models.json` 与 `eval-judge.json` 已就绪，阶段2完成标志全部满足。

**tasks.json 状态更新**：`build-models` 命令会自动更新 `tasks.json` 中的 `models` 字段（驱动模型名称列表）。阶段2完成后，该会话记录包含：
- `skill_name`：任务1 上传 Skill 时写入
- `models`：步骤3 `build-models` 时写入
- `status`：保持 `configuring`，待阶段4提交后更新为 `running`

---

## Red Flags

| 违规行为 | 简洁理由 |
|----------|----------|
| 跳过评委确认步骤直接使用默认评委 | 评委选择影响评测客观性，必须经用户确认 |
| 在驱动模型选择阶段使用评委模型列表 | 驱动模型与评委模型的候选来源不同，不可混用 |
| 多评测对象时只走一次"取到 zip → 上传" | 每个评测对象独立处理 |
| 暴露 `usage` / `source` / `recommend_model_id` 等内部字段 | 实现细节不应展示给用户 |

> 通用违规行为见 [SKILL.md Red Flags](./SKILL.md#red-flags)

---

## 常见错误

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| Skill 名称搜索零结果 | 本地与云端均未命中 | 提示改用方式 2（提供地址）或换名称 |
| 多本地路径与 URL 混合输入 | 不支持的输入形式 | 要求用户重新提供，统一为目录或 zip/URL |
| 自定义模型 API Key 无效 | 用户提供错误凭据 | 提交时报错，提示用户更新凭据 |
| 评委选择后未生成 `eval-judge.json` | `build-models` 命令未执行 | 完成阶段4 步骤1 时统一构建 |

---

## 变量速查

变量定义见 [SKILL.md 变量速查](./SKILL.md#变量速查)。
