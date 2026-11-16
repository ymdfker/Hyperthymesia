# IDE／桌面接入核查与 S9

核查日期：2026-11-15。仓库基线：53396ce（v0.2.4）。本文区分「官方文档确认」「本机程序确认」「配置层实测」「GUI 端到端实测」。前三者均不能替代最后一项。本轮没有调用整理模型或前台模型。

## 1. 各入口读取什么配置

下列 `~` 均指实际运行 agent 的系统用户目录；SSH、WSL、容器中运行时，应在对应环境安装。编辑器外观配置不等于 agent 配置。

| 入口 | 钩子配置 | MCP 配置／入口 | 本轮结论 |
| --- | --- | --- | --- |
| Claude Code VS Code 插件 | `~/.claude/settings.json`；项目 `.claude/settings.json` / `settings.local.json` | 当前安装器写 `~/.claude.json` 或项目 `.mcp.json`；面板 `/mcp` 核对 | 官方确认与 CLI 共享；GUI 未实测 |
| Claude Code JetBrains 插件 | 同 CLI | 同 CLI | 官方说明插件直接运行已安装的 `claude`，不自带 CLI；GUI 未实测 |
| Claude Desktop 的本地 Code 页 | 同 CLI 的 Claude Code 配置 | `~/.claude.json`、项目 `.mcp.json`；也可继承 Desktop chat 的 MCP | 官方确认共享；仅限本地 Code 会话，不把普通 Chat 或云端会话算作通过 |
| Codex IDE 插件、Codex App 本地会话 | `~/.codex/config.toml`；可信项目 `.codex/config.toml`；也支持独立 hooks.json | 同一份 config.toml 的 mcp_servers | 官方确认共享；本机 CLI 0.169.0 已读取真实配置层，GUI 未实测 |
| Qoder IDE／JetBrains 插件 | `~/.qoder/settings.json`、项目 `.qoder/settings.json` / `settings.local.json` | IDE 设置 → MCP → My Servers → Add 打开实际 JSON | 官方确认钩子文件与 CLI 共享，包含本服务需要的五类事件；修改后重启。MCP 文档未明确共享路径，不能只凭 CLI 的 `~/.qoder/mcp.json` 就判定接通 |
| CodeBuddy IDE | `~/.codebuddy/settings.json`、项目 `.codebuddy/settings.json` | CodeBuddy Settings → MCP → Add MCP 打开实际 JSON | 官方支持所需事件；项目配置覆盖用户配置。文档没有确认 IDE 读取 CLI 安装器生成的 settings.local.json，也没有确认 MCP 用户文件共享 |
| WorkBuddy 桌面版 | 本机 5.3.14 默认 `~/.workbuddy/settings.json`，可由运行环境改变 | 本机程序中的用户 MCP 配置入口为配置目录内 mcp.json；界面核对实际服务器 | **源码已修复**：install workbuddy 写桌面目录，install codebuddy 保留 CLI 入口。本机已备份接入并完成启动器/MCP 无模型检查；GUI 问答未测 |
| dsh TUI | 选中 profile 的 `$DSH_HOME/profiles/<profile>/cordis.patch.yml`；桥接读取 `~/.hyperthymesia/dsh-hooks.json` | 同一 profile 的 MCP 插件 | 现有安装器按 profile 接入；web 已通过，TUI 仍待界面验证，不能把 web 的结果直接搬过来 |

依据：[Claude VS Code](https://code.claude.com/docs/en/vs-code)、[Claude JetBrains](https://code.claude.com/docs/en/jetbrains)、[Claude Desktop shared configuration](https://code.claude.com/docs/en/desktop#shared-configuration)、[Codex agent configuration](https://learn.chatgpt.com/docs/developer-settings)、[Qoder hooks](https://docs.qoder.com/extensions/hooks)、[Qoder MCP](https://docs.qoder.com/user-guide/chat/model-context-protocol)、[CodeBuddy IDE hooks](https://www.codebuddy.cn/docs/ide/Features/Hooks)、[CodeBuddy IDE MCP](https://www.codebuddy.cn/docs/ide/User-guide/MCP)。

WorkBuddy 本机证据：`/Applications/WorkBuddy.app/Contents/Resources/app.asar` 中 `getDefaultConfigDirname()` 默认返回 `.workbuddy`；`getWorkbuddyConfigDir()` 允许 WORKBUDDY_CONFIG_DIR；启动时将该目录传入 CODEBUDDY_CONFIG_DIR；自定义 MCP 路径使用 configDir/mcp.json。版本取自安装包 package.json。此证据证明路径区别，不证明真实问答钩子已通过。dsh 依据仓库 install.py 与交接中的 web 实测。

## 2. 每个界面的操作清单

先由维护者准备隔离测试库、已知测试记忆与钩子记录，再让用户操作；不要把测试记忆写进日常库。每种形态只需一次正常问答，另开同项目新会话问一个自然的历史问题，不能明确要求调用记忆工具。启动配置检查不耗模型额度；真正问答与后台写入按宿主计费，执行前单独报预估。WorkBuddy 已观察到便宜整理模型耗时较长，不能承诺所有形态五分钟内结束。

| 入口 | 用户操作（每项最多三步） |
| --- | --- |
| Claude VS Code | ① 重载窗口，在测试目录打开 Claude Code 面板；② `/mcp` 确认 hyperthymesia，正常完成一轮；③ 另开同目录会话提问测试事实。维护者核对 prompt/stop 记录、转录和注入。 |
| Claude JetBrains | ① 在测试项目点击 Claude 图标（确认 CLI 可启动）；② `/mcp` 核对后正常完成一轮；③ 新会话自然追问测试事实，维护者查记录。 |
| Claude Desktop | ① Code 页选本地测试目录；② 检查 MCP 连接并正常完成一轮；③ 新建同目录 Code 会话自然追问，维护者查记录。不要在普通 Chat 页替代测试。 |
| Codex IDE | ① 打开测试项目和 Codex 面板；② 检查 MCP 并按界面提示审核新钩子，正常完成一轮；③ 新会话自然追问，维护者核对真实配置层、钩子记录和注入。 |
| Codex App | ① 选本地测试目录新建会话；② 设置中确认 hyperthymesia，按提示审核钩子，正常完成一轮；③ 新会话自然追问，维护者查记录。 |
| Qoder IDE／JetBrains | ① 重启并打开测试目录；② 设置 → MCP 确认服务器连接，正常完成一轮；③ 新会话自然追问，维护者查钩子和实际转录格式。 |
| CodeBuddy IDE | ① 打开测试目录；② CodeBuddy Settings → MCP 确认连接，正常完成一轮；③ 新会话自然追问，维护者查记录，特别核对项目配置覆盖。 |
| WorkBuddy | ① 完全退出并重启 WorkBuddy，加载已备份接入的桌面配置；② 设置确认 MCP 后正常完成一轮；③ 同一测试目录新会话自然追问，维护者查记录。不能拿 bundled CLI 的结果代替。 |
| dsh TUI | ① 选已经接入的独立 TUI profile 启动；② 正常完成一轮；③ 新会话自然追问，维护者核对 profile、钩子和转录。 |

通过标准：MCP 列出并连接只证明读取服务能启动；还要看到宿主实际触发 UserPromptSubmit/Stop、完整最终回复进入 backlog、来源属于当前会话、后台写入使用本宿主、下一会话实际获得注入，才能记 GUI 通过。单纯回答正确可能来自上文，不能代替这些证据。

当前可用记录：隔离库的 state 数据库 backlog / backlog_agent、projects 下的项目库、logs/hooks.log、整理日志；HYPERTHYMESIA_TRACE 可记录注入字数、宿主与 transcript_path。启动界面时需要让进程继承测试环境，或由维护者准备指向隔离库的包装命令；单在一个终端 export 不代表已经运行的桌面程序会继承。只记录必要证据，不导出凭据。

## 3. S9：项目配置覆盖／关闭用户钩子

这里的核心结论：配置由宿主管理。记忆服务不能越过用户或项目禁用钩子的决定，也不能在自己完全没被启动时主动报告失败。不要自动删除项目配置、强行启用钩子或重复安装来掩盖关闭状态。

| 宿主 | 已确认行为 | 验证程度 |
| --- | --- | --- |
| Claude Code | disableAllHooks 按设置优先级取值；项目 true 可以关闭普通用户钩子；项目 false 也可能覆盖用户 true。组织托管钩子另受管理策略约束。 | 官方文档确认；未做真实宿主触发实验 |
| Codex | 各来源的钩子累加，高层 hook 列表不会简单替换低层；可信项目的 `[features] hooks=false` 可关闭钩子功能；不可信项目层不会按可信项目加载。 | 官方文档＋本机配置层实测，详见下文；未调用模型验证实际事件不再执行 |
| Qoder IDE／JB | 多层 hooks 合并，项目定义同名事件不等于删除用户钩子。修改需重启。某个钩子阻塞还会影响后续执行。 | 官方文档确认；未实测项目空列表／禁用开关，不能套用 Claude 的开关 |
| CodeBuddy IDE | 官方明确项目 `.codebuddy/settings.json` 覆盖用户设置，因此用户级接入存在被项目覆盖的风险。 | 文档确认；具体按整表还是按事件覆盖仍待实测 |
| CodeBuddy CLI | 官方有 disableAllHooks 开关；不能把 IDE 的覆盖规则直接当作 CLI 实测结论。 | 文档确认；具体跨层合并待实测 |
| WorkBuddy 桌面 | 配置目录与 CLI 不同。 | 不能沿用 CodeBuddy CLI 的 S9 结论；待桌面接入修复后验证 |
| dsh | 接入按 profile patch 生效；选择未安装的 profile 不会自动继承另一个 profile 的安装。 | 安装实现确认；项目 patch 与 profile 冲突的优先级还未实测 |

依据：[Claude disableAllHooks](https://code.claude.com/docs/en/hooks#disable-or-remove-hooks)、[Codex hook sources / turn hooks off](https://learn.chatgpt.com/docs/hooks)、[Qoder hooks 合并](https://docs.qoder.com/extensions/hooks#config-file-locations)、[CodeBuddy IDE 配置说明](https://www.codebuddy.cn/docs/ide/Features/Hooks)、[CodeBuddy CLI settings](https://www.codebuddy.ai/docs/cli/settings)。

### Codex 无模型实测

使用本机 codex-cli 0.169.0 的 app-server JSON-RPC config/read（includeLayers=true），只 initialize、读取配置、退出，没有 thread/start、turn/start 或模型请求。

在之前已获批准的 `~/Documents/projects/agent-memtest/compat/codex/proj`：

1. 修改前：项目层 enabled（disabledReason=null），含 UserPromptSubmit / Stop / SessionStart。
2. 先备份 config.toml.s9.bak，临时加 `[features] hooks=false`；再次读取，实际合并后的 features.hooks=false；钩子定义仍存在，因此「文件里有配置」不能证明钩子开启。
3. finally 还原，SHA256 一致；第三次读取关闭值消失，原三类定义仍在。

原始结果：本仓库 `bench/results/s9-codex-config-20261115.json`。配置加载验证通过；**这一步只检查配置层**；后续无模型验证见下节，不将配置层检查冒充全部事件验证。后续验证可使用只写本地标记的钩子，避免调用整理模型；若宿主仍要求付费正常回合，先报额度再执行。

## 4. 版本标签清理

已核实 GitHub Release 列表没有 v0.2.0，远端标签原指向 f4a7a38ab6f1c187ba060bb23677c5b95dead379。已删除远端及本地 v0.2.0 标签；没有删除任何提交，也没有改动 v0.2.1–v0.2.4 或对应 Release。


## 5. 本轮修复与 S9 补验（2026-11-15，后续结果优先于上文初查）

### WorkBuddy 桌面修复

- install workbuddy 独立写桌面目录（默认 ~/.workbuddy，可由 WORKBUDDY_CONFIG_DIR 指定）的 settings.json 和 mcp.json，先解析、备份两份配置，再更新本服务条目；原 CLI 配置不迁移、不删除，install codebuddy 继续使用旧入口。项目级入口沿用 CodeBuddy；尚未据此宣称桌面项目级 GUI 已验收。
- 桌面 MCP 进程明确继承桌面配置目录；后台写入沿用宿主环境，模型倍率读取也按 CODEBUDDY_CONFIG_DIR 选择目录。doctor --agent workbuddy 同样使用桌面目录。
- 本机原 settings.json 已备份为 `~/.workbuddy/settings.json.before-desktop-fix-20261115-164226.bak`。原 mcp.json 不存在，本次新建，未伪造“原 MCP 已备份”。未访问或修改凭据文件。原 ~/.codebuddy/settings.json 哈希未变。
- 本机使用 `~/.local/bin/hyperthymesia-workbuddy` 源码启动器接入；v0.2.4 发行包未变，尚未发布新版本。启动器引用本仓库，移动或删除仓库前需重新部署。
- 已用该启动器在隔离记忆目录完成 MCP initialize / tools/list（返回 memory_read_objects）与 prompt-submit / stop 检查，最终回复正确进入 backlog。**不是桌面真实问答测试**。需要完全退出并重启 WorkBuddy 后加载配置。
- 59 项单元回归全部通过，git diff --check 通过，模型调用 0 次。

### S9 实际结果

| 范围 | 无模型方法 | 结果与边界 |
| --- | --- | --- |
| Claude Code CLI | 自建临时项目，正常确认信任，真实启动钩子向本地文件写标记；不提交用户任务 | 基线 user；项目空表仍 user；同事件 project+user；项目 disableAllHooks=true 后无标记。四组均观察到输入界面。用户配置逐字还原。 |
| Qoder CLI | 同类真实启动测试＋从本机安装包原样提取合并函数和 schema 的离线回放 | 基线 user；空表仍 user；同事件 user+project。禁用组无标记，但未确认终端就绪，**该组不单凭无标记判通过**。原合并代码确认 disableAllHooks=true、hooksConfig.enabled=false 均可成为有效设置，hooks 数组合并。用户配置已还原。 |
| WorkBuddy 内置 CLI（使用桌面配置目录） | 同类真实启动测试；另用官方 config get 查询临时目录 | 基线 user；空表仍 user；同事件 user+project。**无论项目级还是用户级 disableAllHooks=true，SessionStart 仍执行 user 标记**。查询能读到 true，因此配置读取和启动事件执行不同。不能声称该开关能阻止本机版本的启动钩子；未测试其他事件，未猜测内部根因，也未在记忆服务里加另一套开关覆盖宿主行为。 |
| Codex 0.169.0 | app-server config/read，见前节 | 可信项目 hooks=false 有效且完整还原；属于配置层验证，没有发起回合验证后续事件。新钩子信任仍交给用户，不绕过审批。 |
| dsh | 独立 DSH_HOME 和最小 profile，官方 --dump-config，不启动应用、不执行 JS | 项目目录下单放 cordis.patch.yml 不自动加载；显式 --patch 传入 `id: hyperthymesia, disabled: true` 后合成结果确实 disabled=true。没有改用户 web profile。 |

这里完成的是 S9 的配置优先级、合并和可无模型验证的启动行为核查，不是对每个 GUI、每个生命周期事件的全量保证。CodeBuddy IDE 尚无实际界面结果；其官方文档的“覆盖”措辞不能推翻已测内置 CLI 的“合并”结果。Qoder 禁用运行确认、Codex 运行事件、WorkBuddy 非启动事件仍保留未测状态。若必须通过正常问答补验，先报告输入／输出与额度预估，再执行，不偷跑模型。

过程中保留的无效结果：首次 CodeBuddy 查询在受限网络下超时，开放必要网络后才正常；首次 Claude 启动测试未确认临时项目的信任，基线没有标记，不能作为禁用证据；dsh 首个夹具误用了 select 字段，未产生覆盖，改用宿主实际支持的 id 后才验证。没有把这些失败计为通过。

证据与实际验证程序：仓库 `bench/results/s9-20261115/`。其中 Qoder merge 回放只运行安装包提取的合并函数，不等于完整运行配置加载和信任流程。启动测试会备份、暂改并还原用户设置，勿在用户正在使用同一宿主时随意运行。


## 6. S9 剩余项收尾与 WorkBuddy 根因（2026-11-15，最新结果）

本节覆盖 §5 的待验状态。没有调用线上或本地模型，没有读取或修改凭据；没有修改宿主程序、记忆服务产品代码或绕过钩子信任。临时修改的设置均已备份并还原。不是记忆质量测试，也不是各 GUI 的完整读写验收。

### WorkBuddy：开关有值，但执行器没有使用它

结论限定于本机 WorkBuddy **5.3.14** 的内置 CLI 安装包。内置 CLI package.json 的版本写作 0.0.0，不能拿它冒充官网独立 CLI 最新版。文件：`/Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/cli/dist/codebuddy.js`，SHA256 `f46c88ec3b2a206ab5a0d6f2f0261095cf9b609f28edb11040d8ac44143d153f`。

实际调用链为：

```text
SessionHookManager 的事件处理
  → HookManager.hasHooks(event)
  → HookManager.getHooks(event)
      只调用 settingsManager.get("hooks")
      再合并插件和作用域钩子
  → HookManager.executeHooks(event, input)
      匹配、去重后执行本地钩子
```

上述三个实际方法没有读取 disableAllHooks，也没有相应的关闭分支。整个内置 CLI 文件里，该字面量只出现一次，位于 /goal 的说明文字；不能靠这一次字符串搜索作结论，主要依据是执行路径和以下回放。桌面外层 app.asar 也未发现该键，属于辅助证据。

把安装包里的 hasHooks/getHooks/executeHooks 方法原样提取，在隔离环境执行，只把设置读取和最后的命令执行换成本地记录器：disableAllHooks=false 和 true 两组都派发了 SessionStart、UserPromptSubmit、PreToolUse、PostToolUse、Stop、PreCompact、SessionEnd 七类事件；两组读取的设置键都只有 hooks。这是**实际执行器的代码回放**，不是七类事件都在桌面界面里各走了一遍。此前真实启动测试已确认用户级、项目级 true 都挡不住 SessionStart，两项证据吻合。

所以根因不是材料没传到、项目覆盖失败或记忆服务重开了钩子，而是**这份宿主安装包没有把文档中的开关接到执行器上**。官方独立 CLI 文档确实列出该开关，但不能因此假定本机桌面内置版本已经实现：[CodeBuddy settings](https://www.codebuddy.ai/docs/cli/settings)。配置查询读到 true，只证明配置存储／读取成功，不证明功能实现。

本轮不替宿主打补丁，也不在记忆服务里再造一套跨宿主的同名开关。需要停用本服务时，应移除本服务的安装条目并重启宿主，或升级后重新验证宿主开关；没有执行卸载或升级。

### Codex：配置关闭确实阻止实际记录

使用本机 codex-cli 0.169.0、此前已获批准的测试项目和原钩子命令；不更换钩子、不跳过信任审核。临时项目配置先备份，结束后 SHA256 与原文件一致。

为了不花模型额度，配置了一个只返回固定 SSE 文本的 **127.0.0.1 HTTP 夹具**。它不是本地模型，没有推理能力、没有密钥，不记录请求正文或凭据头；使用 requires_openai_auth=false 的独立测试提供方。真实 Codex 客户端仍完整执行一轮提交和结束流程。后台整理指定 fake，仅作用于既有兼容测试库。

| 项目 hooks | 客户端正常完成 | 本地固定响应请求 | prompt 钩子记录 | backlog 完整轮次 |
| --- | --- | --- | --- | --- |
| true | 是 | 1 | 1 | 1 |
| false | 是 | 1 | 0 | 0 |
| true（重新开启） | 是 | 1 | 1 | 1 |

两次开启时固定回复正确进入 backlog；关闭时没有新轮次，不是客户端失败或没收到回复。没有出现钩子信任拒绝。真实模型调用 0；HTTP 夹具的三次请求不能计为三次模型调用。这个实验验证 UserPromptSubmit/Stop 的实际效果，不扩展为全部 Codex 事件或 GUI 已通过。

### Qoder：两种关闭方式都已补上运行确认

本机 qodercli 1.1.89；临时项目、用户设置备份后还原；只启动和发送官方内置 /help，不提交问答任务。测试终端设定正常行列尺寸，正常确认自建项目的信任提示。

| 项目设置 | 启动标记 | 正常模型／ctx 状态栏 | 进程存活 |
| --- | --- | --- | --- |
| 默认开启 | 1 | 是 | 是 |
| disableAllHooks=true | 0 | 是 | 是 |
| hooksConfig.enabled=false | 0 | 是 | 是 |
| 恢复开启 | 1 | 是 | 是 |

因此关闭组不是没启动到可用界面；重新开启也恢复了标记。/help 菜单内容没有被自动检测器识别，**不声称帮助菜单验证通过**，就绪证据是各组实际显示的模型／ctx 0% 状态栏及进程存活。

代码核对：启动配置用 `!disableAllHooks && hooksConfig.enabled` 设置 enableHooks；公共执行路径调用 isAllHooksDisabled()，关闭时过滤用户钩子，保留宿主标为 internal 的内部运行钩子。因此“关闭用户钩子”不等于宿主内部所有工作也停止。

本轮最初两次正向基线未触发，是验证脚本漏识别 Qoder 的 “Do you trust the files in this folder? / Trust folder” 界面；识别后正常确认才继续。失败结果保留，不计通过；没有通过放宽宿主信任来处理。

### S9 当前结论与唯一环境缺项

- Claude：沿用前轮的用户／项目合并及启动关闭实测。
- Codex：补完提交／停止的开启—关闭—再开启运行验证。
- Qoder：补完两种开关的启动运行验证与公共关闭路径核对。
- WorkBuddy 内置 CLI：根因已明确，七类事件共用未检查开关的执行器；应记录为本版本宿主能力缺口，**不是修复后通过**。
- dsh：沿用官方 dump-config 的覆盖验证；显式 patch 才覆盖，不把项目同名文件误当自动加载。
- 独立 CodeBuddy IDE：本机 /Applications 没有该应用，VS Code 扩展目录及常规 JetBrains 应用支持目录也未找到对应插件。**这项仍无实机结果**，未自行下载整个 IDE；不拿 WorkBuddy 的内置 CLI 结果代替。该环境缺项与模型额度无关。

剩余 GUI 完整读写、Windows、一周真实使用与发布任务没有因此自动完成。全部证据、实际脚本与失败夹具保存在 `bench/results/s9-20261115-final/`；本轮没有改产品代码，不需要为文档更新重跑整套单元测试。


### 决策：WorkBuddy 开关问题的处理

用户已确认：本机版本 disableAllHooks 失效记为宿主已知问题，不增加记忆服务补丁，不作为记忆服务待修复项。其实际影响是用户以为关闭后仍可能记录、注入和触发整理；正常开启流程不因该开关缺失而被阻断。需要停用时移除本服务接入并重启。接入是否达到预期，仍以桌面真实问答的写入、新会话读取、质量和开销验收为准。


## 最新状态：WorkBuddy 桌面快捷验收失败（2026-11-15）

用户手动完成真实桌面 3 轮，钩子完整记录 3/3；后台把自己在 ~/.hyperthymesia/writer_work 下的抽取请求也记入积压，进而递归整理。原目标项目写入未完成，事实和对象仍为 0，未继续召回。

已备份并暂停 ~/.workbuddy/settings.json 中本服务的五类钩子，停止锁文件确认的两条后台进程树；MCP 未移除，前台会话、积压和失败库保留。**WorkBuddy 记忆自动记录当前暂停，不要直接还原钩子导致重启递归。** 未修改产品代码、未补写或重跑。

已落盘 rawUsage：桌面前台 663088 token / 5.02 credit；后台 hy4-free 71408 token / 0 credit；合计 734496 token / 5.02 credit，未含中断后尚无用量返回的调用，也不含当前 Codex 协助会话。无无记忆对照，不能全部算作记忆服务额外开销。

完整失败报告与证据：`~/Documents/Codex/2026-11-07/du/workbuddy-quick-acceptance/REPORT.md`。设置备份：`~/.workbuddy/settings.json.before-recursion-pause-20261115-183323.bak`。先诊断并修复内部整理被自身钩子记录的原因，再由用户决定重测；不得把此前 CLI 通过或本次记录完整当作桌面端到端验收通过。


## 后台内部任务隔离已修复，桌面完整链路仍待验收（2026-11-15）

execution.py 为后台及全部模型 CLI 入口统一设置内部标记，覆盖整理、补漏、冲突检查及模型试探；全部钩子在读会话、开库、注入或触发补写之前退出。不依赖宿主禁用开关、目录名或模型判断，前台环境不被标记。

64 项测试通过；原失败 10 条内部请求 × 5 事件共 50 次实际入口回放无新增记录/记忆目录；真实 WorkBuddy 内置后台 CLI 的启动回调确认 marker=1，钩子无副作用退出。全程模型调用 0，未读改凭据。不是桌面真实问答重测。

证据：`~/Documents/Codex/2026-11-07/du/workbuddy-quick-acceptance/internal-isolation-fix/REPORT.md`。旧失败库和积压保持不变，WorkBuddy 用户钩子仍暂停；未恢复、补写或自动重跑。后续须用独立空测试库进行桌面验收并先报额度，不能宣称完整流程已通。源码未提交或发布。


## 2026-11-15 最小修复：后台选模、建议范围与退出诊断

已复用现有端到端验收筛选后台模型，旧简单题缓存不再直接放行。当前WorkBuddy可用列表与本地倍率缓存下，零模型请求选中GLM-5.3-Flash；HY4因历史耗时与输出量未通过准入。无已有验收时最多两个条件/更正/建议准入候选，未通过不退回未验收默认模型；选模不再调用模型整理价格或逐个测价。主写与补漏共用助手建议保存规则，不保留客套、结束语与重复复述，保留具体执行方案和必要条件，不按条数硬砍。新增逐次调用耗时/用量、生命周期到达及后台启动结果日志。保留批量架构、阈值、更正与来源机制。

69项无模型测试通过；原样回放安装包SessionEnd方法后，本服务真实分离进程用fake提供方尾写通过，SessionStart补写也通过。不是桌面退出实测；真实Electron退出是否派发SessionEnd仍待用户动作确认。已备份WorkBuddy设置，仅临时增加无模型退出事件记录器，验证后撤除；MCP、凭据和旧失败库未改。无模型调用、无额度消耗、未发布。历史GLM验收不等于本次新提示已线上验证。

报告和证据：~/Documents/Codex/2026-11-07/du/workbuddy-minimal-fix-20261115/REPORT.md


### WorkBuddy退出标记检查收尾（2026-11-15）

用户已正常退出、重开、再次退出，未收到SessionEnd标记。记录器本地检查有效；宿主日志显示重开后的CLI运行时未就绪即被退出清理，此结果不足以证明正常就绪会话不派发结束事件。真实桌面结束即写仍未通过验收，不把本地回放冒充该项通过。临时记录器已移除，settings.json与测试前备份逐字一致；本检查模型调用0、旧失败库与凭据未动。证据：~/Documents/Codex/2026-11-07/du/workbuddy-minimal-fix-20261115/desktop-exit-result.json。


### WorkBuddy就绪后真实退出验证完成（2026-11-15 22:09）

在CLI host已报告ready、真实已有聊天于22:08:13收到SessionStart（resume）后，用户22:09:02正常退出桌面，宿主记录正常清理和Shutdown complete，但同会话未收到SessionEnd。排除上次尚未就绪因素；不声称已分清宿主不派发还是退出时中断。桌面结束立即尾写不能判通过；现有启动补写已验证，未新增补丁。两个临时标记钩子均已撤除，用户配置与备份逐字一致。无模型调用或额度消耗，未动凭据、MCP和旧失败库。证据：~/Documents/Codex/2026-11-07/du/workbuddy-exit-verification-20261115-220348/REPORT.md。


### 用户决策：暂接受WorkBuddy桌面退出局限（2026-11-15）

用户确认，将本机WorkBuddy 5.3.14桌面退出不能可靠送达SessionEnd记为已知宿主局限，暂不增加补丁。正常接入时，达到阈值的后台写入与已入库记忆读取不直接受影响；未达阈值的尾部靠下次进入会话触发SessionStart后异步补写。仅打开应用停在首页不保证触发；补写未完成前首问可能漏掉尾部信息，完成后需再次提问。不要承诺固定等待时长，也不要声称已查明未派发还是退出途中中断。测试配置已还原，实际用户记忆接入仍暂停，不自动恢复旧失败库。该项从当前修复待办转为已知局限；后续宿主升级时可重新验证。


## Windows实测问题修复（2026-11-16，自动化验证通过，桌面认证待复验）

Qoder用户级MCP改用settings.json；保留其他服务并迁移本服务旧入口。CLI参数绕过Windows CMD，以npm package.json的bin或包装器实际脚本解析Node入口。Qoder后台移除SDK传输入口标记，不抹掉认证位置，不按版本号强制降级。WorkBuddy支持注册安装位置、明确指定脚本及lite构建环境。

BOM兼容覆盖钩子、配置和恢复记录；轮次分配改为事务内递增插入，有host turn ID时幂等且按ID完成，停止覆盖旧轮次。操作系统文件锁替代按mtime推断；异常退出自动释放，新版不抢占仍存活的旧版PID锁。代码快照操作也串行化，附带快照失败不会阻止保存对话。

模型响应的退出状态、鉴权错误和提交字段均检查；不符合提交协议的结果不算成功空写，不推进位置。错误可从write退出码和日志看见。未完成轮次保留原话、记录transcript位置，仅凭明确完成标记和唯一原话匹配恢复；不以超时强制完成或自动弃记。

Windows安装脚本先验证TEMP可写，下载后验证exe启动，宿主接入失败不再打印完成。内存库路径已有HYPERTHYMESIA_HOME，不另加相似别名；解包失败在Python启动之前，源码内的doctor不能拦截bootloader。

仍须真机确认：Windows具体WorkBuddy lite构建的认证可用性、Qoder桌面实际继承的环境、真实MCP工具可见性和完整问答。无模型的模拟入口/Windows构建检查不等于这些已通过。旧自记录材料不按词语或目录名自动删除，凭据与旧失败库不改动。

验证记录：修复分支的Windows、macOS双架构和Linux测试、构建及产物检查已通过（GitHub Actions run 43793133170）。首次Windows失败是新增doctor统计未关闭数据库句柄，修正后通过，失败记录43792685350保留。回归覆盖真实Node参数传递、锁持有进程被结束后重新获得锁、并发回调和BOM，不调用模型。不以这些通过结论代替Windows真实宿主登录和完整问答验收。
