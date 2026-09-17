---
name: silent-failure-triage
description: "命令退出码 0、输出正常，但事情没做成"的判定手册。写 shell 判定逻辑、轮询 CI、宣布"已完成/已合并/已注册/已清理"、批量删除、自测守护进程之前必须读。触发词：静默失败、假成功、退出码、$? 不准、结果为空、看着没动、任务在但没跑、合并没生效、改了没反应、重试没用。
---

# 静默失败分诊（Windows + agent）

这一族唯一的共同点：**成功信号为真，事实为空**。所以规则只有一条——断言的层级必须比"命令自己的输出"更低一层：读回状态、比对 SHA、数命中条数。

## 1. 管道让 `$?` 说谎

- **现象**：`python x.py | tail -3; echo $?` 永远输出 0，脚本崩了也报成功。这是最容易在长会话里连犯三次的同类错误。
- **根因**：`$?` 是管道**最后一个**命令的状态。
- **对策**：要真退出码就别接管道；必须接就 `${PIPESTATUS[0]}`（bash）。判定脚本成败用"退出码 + 关键输出行"**双证据**，不看"有没有报错文案"。
- **判定**：故意让脚本失败一次，对比 `echo $?` 与 `echo ${PIPESTATUS[0]}`；两值不同即确认你在读错的字段。

## 2. 空输出有两种成因，先分清再解读

- **现象**：`if [ -n "$OUT" ]; then ok; else 网络失败; fi` —— 仓库确实没有待办 PR 时输出也是空，于是循环"重试网络"六次，每次都很自信。
- **根因**：把"结果为空"和"取数失败"塞进同一个信号。
- **对策**：失败判据用退出码或 HTTP 码，空值判据用 `--jq 'length'`（显式拿到 `0`）。反过来也成立：**批量删除/清理前，0 命中必须先证明过滤器有效**——喂一条"故意不存在的串"当对照组，同时喂一条已知存在的串证明能命中，然后再相信那个 0。
- **判定**：`git ls-remote` 不带代理时失败只写 stderr、stdout 全空，`| grep` 得空 → 极易被读成"分支已不存在"。看 stderr 与退出码即可分辨。

## 3. 取数失败会伪装成合法数据

- **现象**：逐个 `git log -1` 查远端分支的提交日期，得到**所有分支日期完全相同**。
- **根因**：拉取失败的分支回退到本地缓存/默认对象，日期是同一个兜底值。
- **对策**：多个分支日期全等 = 取数失败信号，不是"它们真的同一天"。要证据用 `git ls-remote --heads` 的 SHA 或 API。
- **判定**：同一条命令带上正确代理后日期即散开 → 确诊。

## 4. 远端 ref 的"假同步"：`packed-refs` 压过 loose 文件

- **现象**：`git fetch` 打印 `a..b main -> origin/main`，看着更新了，但 `git rev-parse origin/main` 纹丝不动；`git update-ref refs/remotes/origin/main <sha>` 也 exit 0 无效，甚至 `.git/refs/remotes/origin/` 目录已被 git 自己清掉，手写报 `No such file or directory`。
- **根因**：该 ref 只存在于 `.git/packed-refs`，loose 文件缺失时写入无处落，packed 条目继续胜出。
- **对策**：`mkdir -p .git/refs/remotes/origin` 后 `printf '%s\n' <sha> > .git/refs/remotes/origin/main`（loose 优先于 packed），再 `git rev-parse origin/main` 验证。
- **判定**：`git show-ref | grep origin/main` 看真实生效值 + `grep origin/main .git/packed-refs`。**这条最危险的后果**：此时 `git reset --hard origin/main` 会静默把工作树拉回旧提交。

## 5. 反过来的"假陈旧"：代理缓存了 ref  advertisement

- **现象**：刚合并完 PR，`git fetch origin main` 成功、exit 0，但 `origin/main` 指向几小时前的提交，当天合并的几条全"不见了"——看起来像远端被 force-push 回滚。
- **根因**：出口代理缓存了 smart HTTP 的 `GET /info/refs?service=git-upload-pack` 响应；而 push 走 POST 不被缓存，于是出现"push 成功 / fetch 拉回旧状态"这种自相矛盾。
- **对策**：换 URL 形态就换缓存键（加 `.git`、加 `www.` 任一）：`git -c http.proxy=http://127.0.0.1:<端口> fetch https://www.github.com/<owner>/<repo>.git main`，再读 `git rev-parse FETCH_HEAD`。
- **判定**：用 API 取权威值 `gh api repos/<owner>/<repo>/branches/main --jq .commit.sha`。**API 说新、fetch 说旧 = 缓存问题，不是仓库问题**。它与 §4、与"真·基线陈旧"（§6）症状几乎相同、处置完全相反，判错会做一堆多余的"补救"写回旧基线。

## 6. 陈旧基线：把队友的产出整片删掉

- **现象**：本地克隆长期未同步，基于几天前的 `main` 开分支并推上去，PR diff 表现为**删除队友这几天全部产出**；评审方直接判定该分支禁止合并。
- **根因**：写操作前没 `git fetch`，或者 fetch 因网络静默失败却没被察觉（"我上次同步过"不是证据）。
- **对策**：任何写之前跑 `git fetch origin && git log --oneline -1 origin/main && git log --oneline origin/main..HEAD`；fetch 报网络错就**停止一切写操作**。合入别人的分支前查三样：`git merge-base <分支> main` 的年龄、`git diff --stat main..<分支>`（净删几千行且 0 新增）、`git ls-tree -r <分支> --name-only` 里关键文件还在不在。
- **判定**：任一异常即禁止合并；三重信号同时异常时不要"先合了再说"。

## 7. `exit 0` 但事情没做成：GitHub 侧三例

- **`gh pr merge`**：可能报 `Post "https://api.github.com/graphql": EOF`，也可能**退出码 0 而 PR 仍是 OPEN**——以为合了其实没合。合并动作之后必须复核 `gh pr view <n> --json state,mergedAt` 看到 `MERGED`；`--delete-branch` 放到确认之后再单独补一次调用。
- **`PATCH` 返回 200 但字段没生效**：改仓库 `topics` 要单独 `PUT /repos/<o>/<r>/topics`，塞在 PATCH 里会被静默忽略。凡"API 调用成功但结果不对"，先 dump 一条原始响应看字段真实值与大小写（CI 的 `status`/`conclusion` 是小写 `completed`/`success`）。
- **403 正文里有关键信息**：例如"make this repository public to enable this feature"——只看状态码会漏掉可执行的下一步。
- **推成功 ≠ 可访问**：仓库仍是 private 时页面 404，而 API 侧 commit 已存在。

## 8. 计划任务：注册了，但永远不会跑

- **现象**：`schtasks /query` 显示 `Status=Ready`、下次运行时间也在未来，但从没真正执行过。
- **根因**：`schtasks /create` 默认写入 `<DisallowStartIfOnBatteries>true</DisallowStartIfOnBatteries>`、`<StopIfGoingOnBatteries>true</StopIfGoingOnBatteries>`、`<LogonType>InteractiveToken</LogonType>`。笔电没插电/没人登录 = 整轮丢失，而且不报错。（实测：`schtasks /query /tn <任务> /xml` 里三个元素俱在。）
- **对策**：注册后立即手动跑一次；笔电上把两个电池开关置 `false`；无人值守要换登录类型并配账号。判断"某个定时任务是否真的在跑"看它**日志尾部的时间戳**，不要看注册没注册。
- **判定（两条都要）**：
  1. `Get-ScheduledTaskInfo -TaskName X` 读 `LastTaskResult`，非 0 即失败，用 `New-Object System.ComponentModel.Win32Exception(<code>).Message` 解文案。实测某长期"看着健康"的任务 `LastTaskResult=2147946720`（`0x800710E0`）而 `Status` 依然正常。
  2. 别按英文标签 grep：中文 Windows 上 `schtasks /fo LIST /v | Select-String "TaskName|Status|Next Run|Last Result"` 实测返回 **0 行**（标签已本地化成"上次结果/下次运行时间"），而退出码仍是 0——于是被误读成"任务不存在"。验证一律走 `/xml`（标签恒英文）或 `Get-ScheduledTask*` 属性。

## 9. `curl` 打回了 HTTP 码，文件却没落盘

- **现象**：`curl -o out.json` 偶发有状态码、无文件，下一步读取报 `No such file or directory`（受限沙箱里更常见）。
- **对策**：要正文就别经文件，直接走 stdout 管道；要落盘就立刻 `test -s out.json && wc -c out.json`。
- **判定**：把 `-w "%{http_code}"` 与 `-s file -a -s file`（存在且非空）当成一对断言，缺一即视为失败。

## 10. 编辑工具会静默丢改动

- **现象**：同一条消息里对**同一个文件**发多个 Edit，每个都回 `Successfully edited`，最终只有一部分生效——新增的定义被同批的循环改动覆盖掉。另一形态：对日志/清单类文件"追加"，实为整段覆盖，历史静默消失。
- **根因**：并行 Edit 各自基于同一份旧快照回写，后写覆盖先写；追加语义被实现成全文件写。
- **对策**：同一文件的多处改动**必须串行**（一次消息一个 Edit），不同文件才可并行；追加时先 `Read` 尾部若干行，把尾部原样保留在新内容开头。
- **判定**：改完逐个复核"每个新增符号还在吗"（`grep -c`），以及行数/段落的增减是否符合预期。只读工具的返回文字必然漏。

## 11. 解释器"存在"是假信号

- **现象**：`command -v python3` 有输出、`Get-Command python3` 也成功，于是选定它写脚本；实际一跑零输出、退出码 49（实测 `python3.exe` 是 0 字节 `ReparsePoint` 桩，`python3 --version` 退出码 49 且 stdout/stderr 全空）。
- **根因**：`%LOCALAPPDATA%\Microsoft\WindowsApps` 在 PATH 上，里面是应用执行别名占位符而非可执行文件。
- **对策**：判定解释器可用性要**真跑一次并看退出码**（`python3 --version` / `python -c "print(1)"`），并把解释器路径写死成绝对路径；多解释器并存时用 `py -0p` 先列清，报"模块不存在"时先确认跑的是哪一个。
- **判定**：`Get-Item (Get-Command X).Source | Select-Object Length,Attributes`——`Length=0` 且含 `ReparsePoint` = 桩，视为不存在。同类：`npx`/`npm` 会同时投放 POSIX / `.ps1` / `.cmd` 三件套，cmd.exe、PowerShell、Git Bash 各取不同那份，所以"同一条命令在不同宿主行为不同"。

## 12. 重试环掩盖错误前提

- **现象**：同一目标动作反复进行（读同一文件、跑同一转换、试同一命令）而中间输出无变化，最坏一次耗掉整轮。
- **根因**：语义/逻辑类失败被当成网络抖动重试。只有网络类值得重试，且次数有限。
- **对策**：**无新进展的同类调用超过 3 次立即停**；止损顺序 = 换工具/换命令形态/换输入形式 → 仍不行就明确报告故障并给人工方案。区分三件事："我在重试" / "我在换办法" / "我在原地打转"。
- **判定**：对自己的调用日志计数——同一 `file_path` 或同一命令行出现 ≥4 次即已命中。

## 复用信号
"命令报成功但结果不对""退出码 0 但什么都没发生""这个目录是空的（其实不是）""任务在但没跑过""PR 说合了但还是 OPEN" → 先怀疑判定层级不够低，而不是怀疑功能坏了。
