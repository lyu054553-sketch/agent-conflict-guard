---
name: ship
description: 从需求到上线的多模型协作流程。Claude Opus 5.5 主控；Gemini 4 Neon 出第二方案和审交互；Kimi K3.1 Pro 审中文文案；GPT-6.2-Astra 和 MiniMax-M3 分写后端；DeepSeek V4.1 Flash 预审；GPT-6.2-Sol 终审；MiniMax-M3.1-Flash 做杂活。用户提新需求、说"按流程做"或"/ship"时使用。
---

# 从需求到上线

你（Claude Opus 5.5）是主控，下面每一步里没写明交给谁的事都由你做。角色和模型对应关系见 CLAUDE.md。

任务文件都写到 `.agents/tasks/<步骤>.md`，结果在 `.agents/out/`。每个阶段结束时用一两句话告诉用户进展。

## 1. 理解需求，两份方案

1. 查代码、查数据、查线上，弄清现状。
2. 写 `.agents/tasks/plan.md`：只放需求原文和必要背景（相关文件路径、约束），**不放你的方案**，让对方独立思考。末尾要求对方输出：方案、关键取舍、风险、不确定的地方。
3. 后台运行 `scripts/agents/ask.sh plan .agents/tasks/plan.md`（Gemini 4 Neon），同时你自己出一份方案。
4. 逐条对比两份方案，合成一份。用表格标清每一条采纳了谁的、没采纳的为什么。
5. **停下来，等用户拍板。**

## 2. 设计稿

1. 出设计稿（页面结构、交互流程、全部文案）。
2. 并行送两份审查：
   - `scripts/agents/ask.sh ux .agents/tasks/ux.md`（Gemini 4 Neon）：交互、流程、边界状态
   - `scripts/agents/ask.sh copy-cn .agents/tasks/copy.md`（Kimi K3.1 Pro）：中文文案是否自然、提示语、空状态、错误信息
3. 取舍、改稿，说明哪些意见没采纳以及原因。

## 3. 定接口和验收标准，派活

把后端拆成块，每块写一张派活单 `.agents/tasks/backend-<名字>.md`：

```markdown
# <一句话说明这块要做什么>

## 背景
<为什么做；相关文件路径>

## 接口
<函数签名 / HTTP 路由 / 数据表结构，写到能直接照着实现的程度>

## 验收标准
- [ ] <可以用测试验证的条目>
- [ ] 新增测试覆盖以上每一条，且 `<测试命令>` 全部通过

## 不要做
<范围外的事、不要改的文件>

## 回执
完成后输出：改了哪些文件、怎么验证的、哪些地方不确定。
```

- 先提交当前改动（脚本要求工作区干净）。
- 运行 `python3 scripts/agents/monitor.py check`，确认没有正在进行的活和这批派活改同样的文件。并行派出的几块，在各自派活单的「不要做」里写明对方负责的文件。
- 按 CLAUDE.md 的规则分配：`scripts/agents/ask.sh backend-hard <派活单> --write`（GPT-6.2-Astra）或 `scripts/agents/ask.sh backend-easy <派活单> --write`（MiniMax-M3）。互不依赖的块可以在后台并行跑。
- 派出去以后你写前端。

## 4. 收活

对每个回来的分支：
1. 读 diff，对照验收标准逐条核对。
2. 在对应的 worktree（`.agents/worktrees/...`）里跑测试。
3. 合格就 `git merge <分支>` 合进当前分支；不合格就写补充说明，再派一次同一个角色，或者自己改。MiniMax-M3 同一块连续失败 2 次，改派给 GPT-6.2-Astra（`backend-hard`）。
4. 合完后删除 worktree：`git worktree remove <路径>`，并删掉分支。

全部合完后跑一遍完整测试。

## 5. 审查和合并请求

1. `scripts/agents/review.sh pre`：DeepSeek V4.1 Flash 预审，你修掉认可的问题。
2. `scripts/agents/review.sh final`：GPT-6.2-Sol 终审，最多 2 轮。第 2 轮后还有分歧，列出来交给用户决定。
3. 写 `.agents/tasks/pr.md`（放 `git log` 和 `git diff --stat` 的输出），用 `scripts/agents/ask.sh chores .agents/tasks/pr.md`（MiniMax-M3.1-Flash）生成 PR 描述和更新日志，你核对后用 `gh pr create` 开合并请求。

## 6. 合并之后

1. `gh pr checks --watch` 等自动检查。失败就修，修完重新推送。
2. 全部通过后 `gh pr merge --squash`（如果用户没有授权自动合并，先问）。
3. 按项目的发布方式发布。
4. 核实线上：访问页面或接口确认功能正常。把错误日志写进任务文件，交给 `chores` 角色（MiniMax-M3.1-Flash）初筛分类，你再判断是否需要回滚或修复。
