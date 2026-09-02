---
name: batch-translate
description: "批量翻译 mqxliff/docx/xlsx/txt：编译项目资源、使用原生子代理翻译与复核、执行项目级 QA，并独立导出。"
---

# batch-translate

用于用户要求批量翻译或续跑翻译文件。源文件始终只读；受管工作副本、状态和导出文件位于 `batch_translate/`。

## 开始前

先确认 Python 3.10 以上，并检查本地工具包和角色是否匹配当前协议：

```powershell
python -c "import sys; assert sys.version_info >= (3, 10), sys.version"
python <skill_dir>\scripts\check_toolkit.py batch_translate
python <skill_dir>\scripts\install_roles.py --check
```

每次续跑只做这两个本地检查，不拉取、不安装依赖。仅在工具包不存在、检查失败、角色未同步或用户明确要求更新时，才安全更新工具包、安装依赖并同步角色；不得删除 `data/`、`exports/` 或本地改动，也不得使用强制重置。

工作区中应保留：

- `data/style_guide.txt`：从用户确认的权威资料编译
- `data/term_base.xlsx`：从用户确认的权威资料编译
- 用户确认的永久 TM：只读，重复源文以已翻译批次覆盖既有 TM
- `data/project_tm_runtime/`：已提交批次自动生成的低优先级运行期 TM
- `data/project_rules/current.json` 和 `data/qa_rules.txt`：项目通用、已审批的 QA revision

永久 TM 优先于运行期 TM。不要修改永久 TM 或用户源文件。

## 初始化与项目规则

1. 扫描项目资料，列出候选的风格指南、术语库和永久 TM，以及已有编译版的路径、大小、修改时间和 SHA-256。
2. 只向用户确认这三项。未确认不得初始化文件或启动翻译角色。
3. 先编译三项资源。运行 `project-config show`；只有 `proposal_compiled=true` 且 `data/qa_rules.txt` 存在时，才向用户说明其 revision、确认来源和规则文件路径，然后复用它。旧 revision 仅作兼容记录，不可作为新版工作流的 QA 规则。
4. 若项目没有有效 revision，或用户明确要求替换规则，才生成一次项目级 QA 提案。提案只能依据项目权威资料、已编译的风格指南和术语库，以及不含文件路径的 TM 元数据；不得引用待译文件、交付文件、导出、`_temp`、旧 QA 快照、状态或单文件样本。
5. 用 `context-analyzer` 生成机器提案，验证后由父代理在对话中用纯文字列出：每条可执行规则、取值、证据、未决问题，以及不会启用的推断项。不得向用户展示 JSON、脚本或内部路径结构。
6. 本轮在展示提案后停止，等待用户明确确认。确认后才编译 revision：

```powershell
python batch_translate/batch.py project-config approve-proposal <proposal.json> --confirmation-summary "用户确认项目级 QA 规则"
```

该命令把提案、审批记录、验证策略和 QA 策略写入不可变的 `data/project_rules/revisions/<revision>/`，并更新可读的 `data/qa_rules.txt`。不要再为每个文件生成 QA 规则，也不要调用旧的 `project-config init/update` 工作流。

项目 QA 规则变更会使所有活动文件的旧任务和 receipt 失效。没有用户确认，不得执行审批命令。

## 初始化文件

创建经确认的参考选择记录后初始化。严格工作流必须绑定当前项目规则 revision 并要求角色 receipt：

```powershell
python batch_translate/batch.py init <source-file> --batch-chars 3000 --context-size 5 --terms batch_translate/data/term_base.xlsx --tm-permanent <permanent-tm.json> --style-guide batch_translate/data/style_guide.txt --reference-selection <reference-selection.json> --require-agent-receipts
```

混合文件会自动锁定已有译文。`preserve_existing=true` 或 `source_locked=true` 的目标必须逐字符保持不变，哪怕是空值；QA 只读审计既有译文，不能借 QA 改写它们。

在第一个批次前运行 `context-split --max-chars 45000`。只有确实超出单份语境容量时才分片；普通文件只启动一个 `context-analyzer`。完成的报告通过 `summary` 写入 `exports/<project-id>/document_summary.md`。

## 原生子代理编排

只能使用原生子代理接口：`spawn_agent`、`wait_agent`、`list_agents`、`send_message`、`followup_task` 和 `interrupt_agent`。用户可通过 `/subagents` 查看会话内子代理。

每个阶段由父代理执行以下顺序：

```powershell
$attempt = python batch_translate/batch.py agent-attempt <stage> --project <project-id> --execution-surface native | ConvertFrom-Json
```

1. 若返回的是同一待完成 attempt，继续观察它，不得再次 spawn 同一角色。
2. 用对应原生角色启动子代理。子代理只读取 `$attempt.agent_input`，只写 `$attempt.outputs` 指定的暂存文件。
3. 父代理从原生调用结果取得真实 `agent_id`。等待期间可用 `list_agents` 查询状态，或用 `send_message`/`followup_task` 补充工作；`wait_agent` 到时只表示没有新事件，不是子代理失败。
4. 子代理真实完成、输出存在且稳定后，由父代理一次性收口：

```powershell
python batch_translate/batch.py agent-finalize <stage> --attempt-dir <attempt-dir> --agent-id <real-agent-id> --role-config <CODEX_HOME>\agents\<stage>.toml --project <project-id>
```

`agent-finalize` 验证稳定输出，写完成事件，原子晋升正式文件并创建 receipt v2；重复调用同一完成 attempt 是幂等的。子代理不得执行收口、receipt 或正式批次写入。

如果原生调用出现工具路由错误或无效等待结果，立即停止本轮后续子代理调用，不创建新 attempt，也不使用替代执行路径。报告已有 attempt 和 `/subagents` 状态；后续会话重新调用 `agent-attempt` 会复用未完成的原生 attempt。

## 批次循环

重复直到所有批次提交：

1. `next` 获取普通/混合文件的翻译任务；全部已有译文时用 `next --review`。
2. 对翻译任务运行 `translator`，并收口为 `_batch_NNN_translated.json`。
3. `review` 创建校对任务；运行 `trans-reviewer`，并收口为 `_batch_NNN_reviewed.json`。
4. 验证校对输出：

```powershell
python batch_translate/scripts/verify_batch.py --stem <project-id>
```

必须核验条目集合、锁定译文、标签、长度、换行和空译文规则。`source_guided` 允许自然重排软换行，但不允许破坏硬段落或堆积标签。

5. 运行 `qa --project <project-id>`。无 finding 时直接 `submit`；有 finding 时运行 `qa-reviewer`，收口两个输出后用 `qa-submit`。QA 代理必须逐条标记 `fixed` 或 `false_positive` 并说明原因，不能改锁定译文。
6. 成功提交会事务写入工作副本和本批运行期 TM。任一校验失败时不推进批次。

翻译、校对和 QA 都读取永久与运行期两层 TM。永久 TM 有精确匹配时优先；角色不得把 TM 匹配当作不经核对的直接替换。

## 导出与验收

完成全部批次后运行：

```powershell
python batch_translate/batch.py export --project <project-id>
python batch_translate/batch.py term-gaps --project <project-id>
```

`export` 必须导出为新文件，拒绝覆盖用户源文件或工作副本。完成前确认：所有批次已提交、receipt 完整、最终验证通过、导出可重新解析、源文件 SHA-256 不变。

## 约束

- 所有 CJK 脚本输出使用 UTF-8。
- 项目专属术语、风格和格式要求只来自编译资源、项目规则和任务 note，不写进通用角色或本 skill。
- 术语缺口只读核查，不自动修改术语库，也不阻塞批次。
- 不把子代理完成回复当成成功依据；以已晋升文件、receipt、验证和提交结果为准。
