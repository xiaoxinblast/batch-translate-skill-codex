---
name: batch-translate
description: "批量翻译工作流（Codex 适配版 v9）。支持 mqxliff/docx/xlsx/txt 的只读源文件初始化、永久/运行期分层 TM、语境分片、分批翻译、逐批校对、程序化 QA、AI QA 复核、严格验证和独立文件导出；Windows 默认 PowerShell。"
---

# batch-translate — 批量翻译工作流

> 已从 Reasonix 迁移至 Codex：`run_skill`/`ask`/`write_file` 已按 Codex 等价流程改写；shell 命令按当前环境执行（Windows 默认 PowerShell）。

## 触发条件

用户表达要批量翻译文件时触发本 skill。如：
- "开始批量翻译"
- "批量翻译这个文件"
- "继续翻译下一批"

## 阶段〇：安装/更新工具包

> ⚠️ **强制步骤**：每次触发本 skill 必须首先执行，不可跳过。

先运行 `python -c "import sys; assert sys.version_info >= (3, 10), sys.version"`，确认解释器为 Python 3.10 或更高版本；再把 `<skill_dir>` 解析为本 `SKILL.md` 所在目录的绝对路径。工具包必须满足 workflow protocol 9。

### 情况 A：`batch_translate/` 不存在

Bash：

```bash
git clone https://github.com/xiaoxinblast/batch-translate.git batch_translate
python <skill_dir>/scripts/check_toolkit.py batch_translate
python -m pip install -r batch_translate/requirements.txt
python <skill_dir>/scripts/install_roles.py
mkdir -p batch_translate/data batch_translate/exports
```

PowerShell（Windows 默认）：

```powershell
git clone https://github.com/xiaoxinblast/batch-translate.git batch_translate
python <skill_dir>\scripts\check_toolkit.py batch_translate
python -m pip install -r batch_translate/requirements.txt
python <skill_dir>\scripts\install_roles.py
New-Item -ItemType Directory -Force batch_translate\data, batch_translate\exports | Out-Null
```

目录结构（按安全 project id 分组；同名源文件冲突时自动加路径哈希）：
- `data/<project-id>/_working_*, batch_state.json, project_identity.json` ← 每个源文件独立
- `data/<project-id>/project_rules/` ← 项目验证/QA 策略快照，工具包更新不得覆盖
- `exports/<project-id>/_batch_NNN_*.json` ← 每个源文件独立
- `exports/<project-id>/document_summary.md` ← 语境分析 sidecar（状态清理后仍保留）
- `data/term_base.xlsx, data/style_guide.txt` ← 共享术语库和风格指南
- 用户指定的永久 TM（例如 `data/tm_memory.json`）← 项目权威参考，只读
- `data/<project-id>/tm_runtime/_batch_NNN.json` ← 当前项目每批独立的运行期 TM，不与永久 TM 合并

> `batch_state.json` 位于 `data/<project-id>/`，**全部批次提交完成后自动清理**；
> 完成后的收尾命令（`export`/`term-gaps`）依赖 `exports/<project-id>/document_summary.md`
> 或批次 JSON，不依赖已清理的状态文件。

### 情况 B：`batch_translate/` 已存在

**必须检查并尝试快进更新到最新版本**。不得删除目录、不得执行 `git reset --hard`；
`data/`、`exports/` 和任何本地改动都必须保留。更新前必须先校验 `origin` 指向
`xiaoxinblast/batch-translate`；若目录不是 Git 仓库、远端不受信任、无法快进或更新后协议不兼容，停止并向用户报告。

Bash：

```bash
cd batch_translate
if [ ! -d .git ]; then
  echo "batch_translate 已存在但不是 Git 仓库；为保护数据，停止自动更新" >&2
  exit 1
else
  python <skill_dir>/scripts/check_toolkit.py . --remote-only
  git fetch origin
  python <skill_dir>/scripts/check_toolkit.py . --revision origin/main
  git merge origin/main --ff-only
fi
mkdir -p data exports
python -m pip install -r requirements.txt
cd ..
python <skill_dir>/scripts/check_toolkit.py batch_translate
python <skill_dir>/scripts/install_roles.py
```

PowerShell（Windows 默认）：

```powershell
Set-Location batch_translate
if (-not (Test-Path .git)) {
  throw "batch_translate 已存在但不是 Git 仓库；为保护数据，停止自动更新"
} else {
  python <skill_dir>\scripts\check_toolkit.py . --remote-only
  git fetch origin
  python <skill_dir>\scripts\check_toolkit.py . --revision origin/main
  git merge origin/main --ff-only
  if ($LASTEXITCODE -ne 0) { throw "batch_translate 无法快进更新，请先处理本地改动或分叉" }
}
New-Item -ItemType Directory -Force data, exports | Out-Null
python -m pip install -r requirements.txt
Set-Location ..
python <skill_dir>\scripts\check_toolkit.py batch_translate
python <skill_dir>\scripts\install_roles.py
```

确认 `batch.py` 可执行且依赖已安装后，进入阶段〇.五。

## 阶段〇.五：项目文件扫描

> ⚠️ **强制步骤**：必须在阶段一之前执行。

### 1. 列出根目录
```bash
ls -la
```

### 2. 多维度 Glob 扫描

- 术语类：`**/*术语*` `**/*用語*` `**/*term*` `**/*glossary*` `**/*词汇*`
- 风格指南类：`**/*翻译指南*` `**/*翻訳*` `**/*方針*` `**/*style*guide*` `**/*ローカライズ*` `**/*本地化*`
- 翻译记忆类：`**/*tm*` `**/*memory*` `**/*翻译记忆*`
- 前作/参考类：`**/*前作*` `**/*master*` `**/*マスター*`

### 3. 评估找到的文件

列出所有找到的文件，标注大小，**同时检查 `batch_translate/data/` 下是否已有编译版**。

**优先级判断原则**：
- `batch_translate/data/` 下的已有编译版优先于项目原始文档
- 根目录文件优先于子目录文件
- 行数/大小大的优先于小的
- `.xlsx` 多 sheet 优先于单 sheet
- 文件修改时间新的优先于旧的

### 4. 确认参考文件来源

> ⚠️ **强制步骤**：扫描后、生成任何文件前，必须询问用户。
> 
> **例外**：若用户触发本 skill 时已明确指定术语库/TM/风格指南来源，跳过 ask 直接使用用户指定值。

向用户展示扫描结果，然后直接向用户提问（可多选），依次询问风格指南、术语库、翻译记忆来源。

> ⚠️ 若用户选择"从源文件导入已有译文"，必须提醒：
> "源文件中已有的译文可能已过时。导入后需逐条核对。"

### 5. 项目规则调查（建议执行）

若未发现项目已有的 `validation_policy.json` 或 `qa_policy.json`，启动 `context-analyzer` 的 `mode=qa_policy_proposal`，读取项目说明、style guide、note、术语和源文件，生成 `_temp/qa_policy_proposal_<project-id>.json`。

- 只把 `explicit` 要求列为可执行候选；`inferred`/`uncertain` 只展示，不自动启用。
- 向用户展示候选规则与证据，用户确认后才写入项目策略快照。
- 未确认的候选不改变默认策略；不得因为单条译文自动放宽全项目校验。
- 已有项目策略时优先使用快照，不重复覆盖；只有用户明确要求重新调查才重新生成提案。

## 阶段一：项目初始化

若目标 project id 下没有 `batch_state.json`，则尚未初始化。不要仅凭源文件 stem 判断；同名源文件可能对应不同 project id。

### 1. 生成风格指南 → `batch_translate/data/style_guide.txt`

> ⚠️ **强制步骤**：必须在 init 之前完成。

- 用 python heredoc：`python << 'PYEOF' ... PYEOF`，输出重定向到文件后读取内容核验
- 必须包含：弯引号规范、破折号/省略号规范，以及完整「日中翻译注意事项（附正反示例）」一节（九项规则 + 正反示例，内容见本 skill 的 `references/ja-sc-style-notes.md`，直接复制该节写入）
- **必须用文件写入工具（Codex 中为 apply_patch）将风格指南写入文件**

> **职责边界（强制）**：本 skill 与子代理角色文件只写通用流程与通用翻译准则；项目专属规则（术语、风格、特殊条目类型等）一律由编译后的 `style_guide.txt`、`term_base.xlsx`、`note`、语境分析报告注入，禁止写入角色文件或本 skill。

### 2. 生成术语库 → `batch_translate/data/term_base.xlsx`

- ⚠️ 读取参考文件时必须读取全部行，禁止截断
- 自适应识别列结构
- 以 xlsx 三列格式写入：`原文(ja) | 译文(zh) | 注释`

### 3. 创建翻译记忆

根据用户选择创建或导入**永久 TM**。它只作为权威参考，工作流不会写回该文件；运行期 TM 由每次 `submit` 自动按批生成。

### 4. 运行 init

`init` 只读取用户指定的源文件，并在 `batch_translate/data/<project-id>/` 创建受管工作副本；
后续提交只修改工作副本和工作 JSON，绝不写回用户源文件。

```bash
python batch_translate/batch.py init <源文件> \
  --batch-chars 3000 --context-size 5 \
  --terms batch_translate/data/term_base.xlsx \
  --tm-permanent batch_translate/data/tm_memory.json \
  --style-guide batch_translate/data/style_guide.txt
```

PowerShell（Windows 默认，单行写法）：

```powershell
python batch_translate/batch.py init <源文件> --batch-chars 3000 --context-size 5 --terms batch_translate/data/term_base.xlsx --tm-permanent batch_translate/data/tm_memory.json --style-guide batch_translate/data/style_guide.txt
```

可选参数：

- xlsx/xlsm：`--source-col C --target-col D --header-row 3 --sheet <名称>`；`--sheet "*"` 处理全部工作表。
- 项目校验策略：`--validation-policy <validation_policy.json>`。仅用它声明项目允许的例外，不得修改通用校验器硬编码项目规则。
- 项目 QA 策略：`--qa-policy <qa_policy.json>`。初始化后会复制为 `data/<project-id>/project_rules/qa_policy.json` 快照。
- 永久 TM：`--tm-permanent <tm.json>`；旧参数 `--tm <tm.json>` 仍作为只读永久 TM 别名保留。可选 `--tm-runtime-dir <目录>` 覆盖默认的 `data/<project-id>/tm_runtime/`。
- 项目选择：`--project <project-id>` 可显式命名；省略时优先使用 stem，同名冲突自动附加路径哈希。重复初始化现有状态会被拒绝，确需重建时显式使用 `--force-reinit`。

### 4.5. 模式判定

> ⚠️ **强制步骤**。init 已自动检测并打印（如 `🔀 混合文件: 511/1491 条已有译文`）。

- **全部有译文 = 总数** → `batch.py next --review`（跳过翻译，直接校对）
- **混合 / 全部无译文** → `batch.py next`（translate 模式自动锁定已有译文，只翻译空条目）

> 混合模式中，`batch.py next` 会自动为已有 `target` 的条目注入 `locked=true`，防止翻译代理改写既有译文。源文件自身锁定的条目另带 `source_locked=true`，并同样标记 `locked=true`；其 target 可以为空且必须原样保留。无需外部手动脚本。

### 5. 全量语境分析

> ⚠️ **强制步骤**。

先生成语境分析分片清单：

```powershell
python batch_translate/batch.py context-split --max-chars 60000 --project <project-id>
```

读取 `exports/<project-id>/context_parts/context_manifest.json`：

- `total_parts=1`：启动一次 `context-analyzer`，直接读取完整 `_working.json`。
- `total_parts>1`：每片分别启动 `context-analyzer`，输入对应 `context_part_NNN.json`，报告写到项目 `_temp/`；全部完成后运行 `context-pack <报告...> --project <project-id>`，再让一个 `context-analyzer` 读取生成的 `context_merge_task.json`，综合为最终全局报告。

分析员必须把最终完整报告写入任务指定的文件（如 `_temp/context_analysis_<project-id>.md`），回复只留摘要。
返回后确认报告文件完整，然后写入状态并保留 sidecar：

```powershell
python batch_translate/batch.py summary _temp/context_analysis_<project-id>.md --project <project-id>
```

该命令同时写入 `batch_state.json` 的 `document_summary` 与 `exports/<project-id>/document_summary.md`。

### 6. 术语缺口核查（只读）

若语境分析报告含「疑似术语库未覆盖的专名」清单，核查术语库是否已存在。**不询问用户、不写入术语库、不阻塞流程**。

### 7. 续跑/复跑（可选）

已完成或中断的批次，可用 `init --resume <已交付/源文件名.mqxliff>` 或 `data/<project-id>/_working_*.mqxliff` 重新初始化：

- 状态文件已存在 → 不覆盖，直接运行 `next` 继续
- 状态已清理 → 从带译文文件重新初始化，已有译文自动锁定
- 若 `exports/<project-id>/document_summary.md` 已存在，跳过本阶段第 5 步（语境分析 + summary），直接进入阶段二

## 阶段二：自动循环

反复执行以下步骤直到全部批次完成。

### Step 1: 获取当前批

```bash
python batch_translate/batch.py next        # 普通/混合文件（自动锁定已有译文）
python batch_translate/batch.py next --review  # 全译文文件（跳过翻译）
```

任务 JSON 中的 `tm_matches`/`tm_fragments` 来自永久 TM，`runtime_tm_matches`/`runtime_tm_fragments`
来自本项目已经提交的各批运行期 TM。翻译和校对都读取两层；永久 TM 是权威层，若两层冲突必须优先参考永久层。

### Step 2: 翻译（仅 translate 模式）

启动 `translator` 子代理角色（角色文件：`~/.codex/agents/translator.toml`）。任务参数中必须使用**绝对路径**指定输入输出文件（从 `batch_state.json` 的 `stem` 推导）。

- source_locked=true 的条目：源文件自身锁定，保留 target 不变，**即使 target 为空也严禁填充或改动**
- source_locked 缺失且 locked=true 的条目：混合模式的已有译文，保留已填 target 不变
- locked=false 的条目：从零翻译
- 每条 `validation` 是该条最终生效的标签、长度、换行和空译文规则；角色必须逐条遵守，不得用通用默认覆盖项目策略

### Step 3: 生成校对文件（仅 translate 模式）

```bash
python batch_translate/batch.py review _batch_NNN_translated.json
```

### Step 4: 校对（共用）

启动 `trans-reviewer` 子代理角色（角色文件：`~/.codex/agents/trans-reviewer.toml`）。任务参数中必须使用**绝对路径**。

> source_locked=true 的条目**严禁修改**；混合模式的 locked=true 既有译文在翻译→校对链路中同样严禁修改。`next --review` 的普通已有译文为 locked=false，应正常校对。

> ⚠️ **落盘检查（强制）**：校对员返回后，确认 `_batch_NNN_reviewed.json` **已实际写入且内容符合要求**：
> 文件存在且非空、mtime 已更新、条目数 = N、id 全覆盖、locked 条目未改动、follow-up 指定的 id 已生效。
> 不满足则退回 Step 4 重跑，或由根代理机械修正后复验，再进入 Step 4.5。

### Step 4.5: 机制化验证校对 JSON

```bash
python batch_translate/scripts/verify_batch.py --stem <project-id>
```

> 脚本内置 UTF-8 输出，无 GBK 编码问题；可连续调用不会被 loop guard 拦截。

**分级处理**：
- `RESULT: PASS (...)` exit 0 → 进入 Step 4.6
- `FATAL:` 非 0 退出码 → 退回 Step 4 重跑
- `WARNING:` + `RESULT: BLOCKED`（exit 3）→ 退回 Step 4 修正后重跑；仅当项目规则明确允许时才可同时加 `--allow-warnings --warning-reason "<具体原因>"` 放行，再进入 Step 4.6

默认校验要求：批次 id 集合精确一致、id/target 类型正确、非锁定项 target 非空、locked target 原样保留；仅 source_locked=true 的空 target 可直接通过、
除 `br` 外的标签序列精确一致、无裸标签、满足 `maxlengthchars`。默认不强制换行数量一致；项目若需更严格或确有例外，
通过 `validation_policy.json` 统一配置，Step 4.5 与 submit 使用同一策略。

### Step 4.6: 程序化 QA

```powershell
python batch_translate/batch.py qa --project <project-id>
```

该命令读取 `_batch_NNN_reviewed.json`，先重复硬性校验，再运行 QA 规则并生成：

```text
exports/<project-id>/_batch_NNN_qa_task.json
```

默认 QA 包括精确 TM 译文不一致、占位符/转义序列、数字、URL/邮箱、空格、括号、疑似未翻译、长度比例、术语一致性和重复译法；换行数量检查默认关闭，可在项目 `qa_policy.json` 中显式启用。精确 TM 检查先使用永久 TM；只有永久层没有精确匹配时才使用运行期 TM，永久与运行期译文冲突时以永久层为准。locked=true/source_locked=true 条目跳过可修改型 QA。

- 无 finding：QA 状态标记为 `clean`，直接进入 Step 5 提交。
- 有 finding：启动 `qa-reviewer`，不得直接 submit。

### Step 4.7: QA 代理复核

`qa-reviewer` 必须使用绝对路径读取 QA task，并实际写入：

```text
_batch_NNN_qa_reviewed.json
_batch_NNN_qa_report.json
```

QA task 中的 `qa_reviewed_path` 与 `qa_report_path` 是本批唯一有效的绝对输出路径；`qa-submit` 会拒绝路径不一致的文件。

报告必须逐条给出 `fixed` 或 `false_positive` 及理由；遗漏、重复、`unresolved` 或修改锁定条目都必须退回重跑。返回后检查两个文件存在、非空、ID 全覆盖、locked 条目未改变。

### Step 4.8: 提交 QA 结果

```powershell
python batch_translate/batch.py qa-submit _batch_NNN_qa_reviewed.json --report _batch_NNN_qa_report.json --project <project-id>
```

`qa-submit` 会重新执行硬性验证和 QA；修正后仍存在的 finding 或新产生的 finding 都阻断提交。只有通过后才执行事务写回并进入下一批。
### Step 5: 提交并推进（无 QA finding 时）

```bash
python batch_translate/batch.py submit _batch_NNN_reviewed.json
```

submit 先完整校验，再以事务方式执行 write + 当前批运行期 TM 写入 + 重新 parse + 状态推进。
永久 TM 始终只读；成功提交会生成 `data/<project-id>/tm_runtime/_batch_NNN.json`，只包含当前批已确认译文，不会与永久 TM 合并。任一步失败都会回滚工作文件、工作 JSON、当前批运行期 TM、state 和 manifest，不会留下半提交状态。成功后回到 Step 1。
submit 遇到 warning 时默认阻断；若明确授权，必须同时传 `--allow-warnings --warning-reason "<具体原因>"`，理由和 warning 会写入 state，并在完成后保留到 manifest。

### 完成

全部批次完成后，`batch.py submit` 自动清理状态文件。随后执行收尾并告知用户完成：

完成后的 `exports/<project-id>/project_manifest.json` 会保留永久 TM 路径和运行期 TM 文件清单；`refresh`/恢复时继续按两层读取。

```powershell
# 按原格式导出最终译文（默认写入项目 已交付/<原文件名>；已存在需 --force）
python batch_translate/batch.py export

# 生成术语缺口待确认清单（默认 _temp/term_gaps_<project-id>.md）
python batch_translate/batch.py term-gaps
```

`export` 支持 mqxliff/docx/xlsx/xlsm/txt，并先写候选文件、重新解析校验，再原子放入交付路径。
导出目标必须是新文件；即使使用 `--force`，也拒绝覆盖用户源文件或受管工作副本。

## Shell 命令规范

- **所有 Python 脚本默认在开头加 UTF-8 输出**：`import sys; sys.stdout.reconfigure(encoding="utf-8")`（Windows 优先用此方法）
- **独立 `.py` 脚本文件**优先于 heredoc（避免 GBK 编码和 loop guard 问题），如 `batch_translate/scripts/verify_batch.py`
- **含中文/emoji 输出时**：优先使用独立脚本文件
- **pip**：用 `python -m pip install` 而非 `pip install`

## 常见坑（通用）

- **XML 实体**：译文正文里的 `&`、`<` 等字符由工具在写回时自动转义（lxml 序列化），不要手写 `&amp;`；也不要改动 `<tag .../>` 标签标记。
- **项目特例**：占位符、换行、空译文或标签差异是否允许，以项目 style_guide/instructions/note 和 `validation_policy.json` 为准；不得在通用 Skill、角色或校验代码中硬编码某个项目的标签名。
- **Windows 控制台 GBK 乱码**：脚本已内置 UTF-8 输出；如仍乱码，可先执行 `chcp 65001` 或设置 `$env:PYTHONIOENCODING='utf-8'`。

## 子代理角色（Codex）

四个子代理已从技能改为 Codex 自定义角色，角色文件位于 `~/.codex/agents/`（个人级）：

- `context-analyzer.toml`：`gpt-5.6-luna` + `max`，用于全量或分片语境扫描
- `translator.toml`：`gpt-5.6-sol` + `high`，用于逐条翻译
- `trans-reviewer.toml`：`gpt-5.6-sol` + `high`，用于逐条校对
- `qa-reviewer.toml`：`gpt-5.6-luna` + `max`，用于复核程序化 QA finding
- **临时文件纪律**：子代理如需辅助脚本/中间文件，一律放项目 `_temp/` 或 `_temp_scripts/`，用后删除；禁止在 `batch_translate/`（data、exports 为受管目录）内创建文件。
