# Windows Agent Failure Modes

**在 Windows 上跑 AI coding agent 反复踩到的失效模式，以及踩完之后定下的判据。**

10 个 Agent Skill（约定格式：每个目录一份 `SKILL.md`，frontmatter 的 `description` 决定 agent 何时加载它）。
内容只有一类东西：**命令返回成功了，但事情没成**。不是"最佳实践"清单，而是
"这一天白干了，因为 X" 之后写下来的现象 / 根因 / 对策 / 判定。中文为主，命令示例面向 Windows + Git Bash / PowerShell。

## 装机

把 `skills/` 下你想用的目录整个复制进你 agent 的技能目录即可（Claude Code `~/.claude/skills`、
Codex `~/.codex/skills`、或任何读 `~/.agents/skills` 的客户端）：

```bash
cp -r skills/* ~/.claude/skills/
```

无需重启；agent 会在匹配的场景自动读取。不想用 agent 的话，当普通故障排查手册读也行——
多数节末尾有一行独立的**判定**（可以直接贴进终端的命令），少数节把命令写在代码块或内联反引号里。
确切数字别信某一句话：`python scripts/check.py check` 会把缺判定行、缺环境戳的节逐个列出来，`stats` 给总数。

## 清单

| Skill | 一句话 |
|---|---|
| [shell-quoting-and-path-forms](skills/shell-quoting-and-path-forms/SKILL.md) | Git Bash/MSYS 的引号与路径形态：命令替换吃掉反引号、heredoc 吞反斜杠、`/d/` 与 `/tmp` 原生程序不认、`//F` 被重写后静默失败、含空格路径被拆成多参数、`$(…)` 剥掉尾换行造成哈希假不等、过 260 字符后半数工具连"文件存在"都看不见、junction 各家答"不是链接"而 `del /f /s /q` 会吃掉目标 |
| [silent-failure-triage](skills/silent-failure-triage/SKILL.md) | "退出码 0 但没做成"的总账：管道让 `$?` 说谎、空输出的三种成因（含下游工具没装时字段变空串而退出码仍是 0）、假同步与假陈旧、计划任务注册了却永不运行、解释器"存在"是 0 字节壳 |
| [windows-text-encoding](skills/windows-text-encoding/SKILL.md) | 编码、BOM 与行尾：`.ps1` 要 BOM 而 `.bat` 不能要、`Get-Content` 默认 ANSI 读回即永久损坏、控制台代码页 vs 文件真字节、兜底代码被自己的 `except: pass` 吃掉、`core.autocrlf` 静默改字节让哈希校验说谎、"默认编码"是每个客户端各自的默认值而退出码全是 0 |
| [git-ref-plumbing-on-windows](skills/git-ref-plumbing-on-windows/SKILL.md) | 绕开正常 checkout 之后要还的债：MSYS 吞掉带斜杠的 ref 写入、`commit-tree` 索引残留、worktree 凭空删文件、对象库损坏别增量救 |
| [github-network-and-api-fallback](skills/github-network-and-api-fallback/SKILL.md) | GitHub 网络分层排障 + REST 兜底：git 不读系统代理、TCP 通而 TLS 挂、Schannel 与 OpenSSL 结论相反、`postBuffer` 500MB OOM、push 静默失败改走 Contents API、逐对象核对远端时的三处假警报 |
| [python-silent-data-errors](skills/python-silent-data-errors/SKILL.md) | Python 读写数据的不报错错误：`open()` 默认编码不是 UTF-8、`csv.writer` 少 `newline=''` 每行夹空行、pandas 3.x 起 `dtype == object` 恒假、`to_datetime` 静默吞值 |
| [runtime-resolution-and-abi](skills/runtime-resolution-and-abi/SKILL.md) | 到底哪个解释器在跑：App Execution Alias 存根、`py -0p` 列出不存在的路径、原生模块 ABI 不匹配、PATH 顺序随 shell 变、venv 没激活而 pip 装到全局 |
| [agent-runtime-boundaries](skills/agent-runtime-boundaries/SKILL.md) | Agent 自己的环境边界：调用结束回收全部子进程、独立回环与 overlay 临时盘、本地操作报外联错、单命令超时、长任务断点续传、越界写入是等待授权不是失败、共享库的写通道报内部错时先读链尾再重试 |
| [chromium-cdp-on-windows](skills/chromium-cdp-on-windows/SKILL.md) | CDP 操控真实 Chrome：默认 profile 禁调试端口、Chrome 不继承环境代理、⛔关掉最后一个 page 会让浏览器整体退出、target 堆积致握手挂起、Cookie 继承的前置顺序 |
| [stale-output-layers](skills/stale-output-layers/SKILL.md) | "改了没生效"的五层定位：源码 / 构建 / 服务 / 渲染 / 部署，每层一条独立判据；Service Worker 清理的两个顺序约束、备份放项目内会弄坏构建 |

## 结构约定

- 每条固定四段：**现象 → 根因 → 对策 → 判定**。判定是可执行命令，不是形容词。
- 新增节末尾带一行环境戳：`- **验证于**：<OS 版本> · <shell 与版本> · <相关工具版本> · <日期>`——
  这些结论全部环境相关，没戳就不知道适用范围。**存量条目不批量补戳**（补=造数据），只在新写或改动时加。
- 跨文件引用只写**技能名 + 节号**（如 `silent-failure-triage §10`），不写路径，避免目录移动后引用悬空。
- 例子中的账号、端口、目录一律是占位符（`<owner>/<repo>`、`<端口>`、`<项目>`）。
- 自查：`python scripts/check.py selftest`（先证明过滤器会响），再 `python scripts/check.py check`
  （结构 / 引用 / 行尾 / 出站红线）。它自带正负对照，所以那个 `0 error` 才是结论而不是沉默。

## 这些结论从哪来，边界在哪

诚实版说明：

- 标注 **本机实测** 的条目是在一台 Windows 11 + Git Bash + 中文（GBK/cp936）环境里跑出来的，退出码、字节、文件属性都取到过；
  其余来自长期项目复盘，属"重复撞到过的现象"，不是受控实验。
- **环境相关，不是普适定律**：盘符、默认代码页、代理软件、Chrome 版本策略、pandas 版本行为都会变。所以每条都配了判定动作——
  先跑判定，再决定要不要照抄对策。
- 面向的场景是"agent 在 Windows 上执行命令"，因此很多条目本质是**验证纪律**（别信退出码、别信 `Successfully edited`、
  别信子代理的自述、别把 0 命中当结论）。这类内容在 macOS/Linux 上同样成立，只是触发的具体报错不同。

## 许可与贡献

MIT。署名见 [LICENSE](LICENSE)。
发现自己这边有不同结论的（版本、地区、代理软件都会造成差异），开 issue 或 PR：请带上**你实测到的退出码/输出**，
只写"这样不对"没法并进来。
