---
name: git-ref-plumbing-on-windows
description: Git for Windows / Git Bash 里 git 引用层与索引层的静默失效，以及 plumbing 提交的安全用法。绕开正常 checkout、手搓提交、批量删分支、回滚之前读。触发词：update-ref 无效、unborn branch、checkout -b 回滚、commit-tree、write-tree、索引残留、文件莫名被删、packed-refs、worktree、force-with-lease、git add -A、filter-branch -d、TMP_DIR。
agent_created: true
---

# Git 引用与索引（Windows）

本族的高频特征：**git 报 exit 0，坏的是 `.git` 里的状态**，而状态错误要到下一次操作才暴露，那时已经很难归因。凡动过 plumbing，就当自己欠一次验证。

## 1. 带斜杠的 ref 写入：旧版记为"MSYS 吞掉"，本机同版本三次未复现 ⇒ 别当既定行为，但判据要留着

- **原始事故（现已无法复现，保留以备对账）**：`git update-ref refs/heads/agent/writer/<名> <sha>` 或 `git checkout -B <含斜杠分支>` 返回 0，而 `.git/refs/heads/...` 不存在、HEAD 变 unborn；objects 与工作区写入都正常，只有 ref 这一层回滚。
- **复测取值（同机同版本，2026-09-17 两轮 + 2026-09-18 一轮）**：`update-ref` 退出码 **0** 且 ref 文件**存在**（41 字节）、`git rev-parse --verify` 退出码 **0**；`checkout -B agent/writer/<名>` 后 `branch --show-current` 正常报出该名、`symbolic-ref HEAD` 就指向它，没有 unborn；全新 clone 与既有 clone 一致。⇒ **不要再把"斜杠 ref 被吞"当成本机默认预期**，也别在 `update-ref` 成功时怀疑它没生效。
- **根因（假设，未被复现支持）**：MSYS 的路径转换把 `a/b/c` 形态的 ref 当文件系统路径处理。若在别的 MSYS/git 组合上真命中，补准确版本号回来，本节结论按版本号收窄而不是改写。
- **对策（只在命中时用）**：
  - 文件系统直写：`mkdir -p .git/refs/heads/<上级目录> && printf '%s\n' <SHA> > .git/refs/heads/<上级>/<名字>`；
  - 或者干脆不在本地建 ref，**裸 SHA 推到远端建分支**：`git push origin <SHA>:refs/heads/<branch>`，之后 `git fetch && git reset --hard origin/<branch>` 对齐本地。
- **判定（与命不命中本条无关，任何 ref 写入后都跑）**：`git rev-parse --verify refs/heads/<branch>` 退出码 0 **且** `.git/refs/heads/<路径>` 文件存在。两个都读，才分得开"ref 根本没写进去"和"写进去了但不是你以为的那个名字"——只看其中一个，前一种会伪装成后一种。
- **注意**：裸 SHA 推送后本地没有 `origin/<branch>` 跟踪引用，后续引用一律用 `FETCH_HEAD`（见 §5）。

- **验证于**：Windows 11 家庭中文版 10.0.26200.9457 · Git Bash 5.2.37 · git 2.53.0.windows.2 · 2026-09-17 首发，2026-09-18 第三次复跑后降级

## 2. `commit-tree` 之后索引不会自动复位

- **现象**：用 plumbing 造提交，"本次只改 2 个文件"的提交实际含 20 个文件，还以 `main` 为父（与另一条分支内容重复）。
- **根因**：`commit-tree` 只造对象，不动 HEAD 也不动索引；索引里还留着上一批已提交的改动，下一次 `git write-tree` 会把它们再打进去一次。
- **对策**：**每次 plumbing 提交完立刻用 `git reset --mixed <新HEAD>` 复位索引**。单写 `git read-tree <新HEAD>` 是不够的：`commit-tree` 不动 HEAD，比较基准仍是旧提交，实测索引差异 **1 → 1 原样不动**，它在这里是个幂等空操作；真正把差异抹平的是把分支指到新提交（`git update-ref refs/heads/<branch> <新SHA>`，此后 `git diff --cached` 自然为空）。只有当 HEAD 已经被移过去之后，`read-tree` 才等于"复位"——顺序不同，看到的差别就不同。要精确控制内容就逐条 `update-index`：
  ```bash
  W=$(git rev-parse :path/to/a.md)          # 暂存区里那份 blob
  git read-tree main                        # 索引 = main 的树
  git update-index --add --cacheinfo 100644,$W,path/to/a.md
  git diff --cached --stat                  # 人肉确认只有你要的那几个
  SHA=$(git commit-tree "$(git write-tree)" -p main -F .git/msg.txt)
  ```
- **判定**：提交后 `git diff --stat <parent> <new>`，文件数远超预期即中招。

- **验证于**：Windows 11 家庭中文版 10.0.26200.9457 · Git Bash 5.2.37 · git 2.53.0.windows.2 · 2026-09-17 首发，2026-09-18 复测改对策
- **复测确认**：索引里先留 20 个文件的暂存改动、随后只 `git add` 2 个文件，`git write-tree` + `git commit-tree` 造出的提交实测为 `16 files changed, 18 insertions(+), 1 deletion(-)` —— 现象成立。`git reset --mixed HEAD` 复位索引有效（`git diff --cached --name-only` 由 1 归 0）。

## 3. 绕开 checkout 切分支 → 上一分支的文件以 staged 形态残留

- **现象**：`read-tree`/`checkout-index` 切完分支，`git status` 里出现不属于当前分支的文件，且是已暂存状态。
- **对策**：凡是绕开正常 checkout 的手法，收尾固定 `git reset --hard <目标SHA>` + `git status` 双确认。
- **前提（重要）**：`reset --hard` 只在**工作树本来就该被丢弃**时用；有未提交改动时它会连你的改动一起抹掉。日常回滚优先 `git revert HEAD`（造一条反向提交，历史不断、不丢工作区）；`revert` 因冲突失败时先 `git stash` 再试，仍不行就从上一个提交里把文件内容读出来覆盖回去。
- **判定**：切完分支 `git status --porcelain` 必须为空，非空就当场处理，别带着脏状态继续干活。

- **验证于**：Windows 11 家庭中文版 10.0.26200.9457 · Git Bash 5.2.37 · git 2.53.0.windows.2 · 2026-09-17
- **实测取值**：在 bA（含 `newA.txt`）上执行 `git read-tree -m -u bB`，退出码 **0**、HEAD 仍在 bA，`git status --porcelain` 得到 `D  newA.txt`（1 行，已暂存形态），该文件已从工作区消失；`git read-tree --reset -u bB` 结果相同。对策 `git reset --hard bB` 后 `git status --porcelain` 为 **0** 行、`git rev-parse HEAD` 与 bB 相等。

## 4. worktree 会凭空"删除"文件；恢复命令要先分清索引动没动

- **现象**：`git status` 突然满屏 `D`，但你没执行任何删除动作。
- **两态（对策不同，先分清）**：
  - **① 索引完好、只有工作区文件被外部删掉** → porcelain 是 ` D`（未暂存）。`git checkout -- .` 退出码 **0**、porcelain 归 0、文件回来。
  - **② 索引也被清空了**（例如谁跑了 `git read-tree --reset -u <空树>`）→ porcelain 变 `D `（已暂存）。此时 `git checkout -- .` 报 `error: pathspec '.' did not match any file(s) known to git`、**退出码 1**、**一个文件都没恢复**；能用的是 `git checkout HEAD -- .` 与 `git read-tree --reset -u HEAD`，两者实测都把 porcelain 归 0、文件恢复。
- **裁决记录**：上一轮复测把 ② 记成"退出码仍是 0、典型的 0 但没做成"，**这条不采纳**：同一种状态下用四种方式读退出码（裸跑、命令替换捕获、Node `spawnSync`、PowerShell `$LASTEXITCODE`）拿到的都是 **1**，只有把命令接进管道再读 `$?` 才是 0——那正是 `silent-failure-triage §1` 记的那条坑，别把它当 git 的行为。② 仍然是真陷阱，但它是**响的**（有 error 行 + 非 0），别指望它静默。
- **对策（通用）**：动手前 `git status --porcelain` 拍快照，看首列还是第二列有 `D` 来定态；恢复后必须再读一次 porcelain 归 0，不要凭命令自述。
- **判定**：满屏 `D` 且自己没删过 → 就是它，不要去查是谁运行的清理脚本；`checkout -- .` 之后 porcelain 没归 0 → 你在 ② 态，换 `checkout HEAD -- .`。

- **验证于**：Windows 11 家庭中文版 10.0.26200.9457 · Git Bash 5.2.37 · git 2.53.0.windows.2 · Node v24.18.0 · PowerShell 5.1 · 2026-09-17 首发，2026-09-18 拆两态并更正退出码读数

## 5. 含斜杠分支 fetch 后没有 `origin/<name>`

- **现象**：`git fetch origin agent/writer/claim` 成功，但 `git log origin/agent/writer/claim` 报 `ambiguous argument`。
- **根因**：单分支 fetch 不生成对应的远程跟踪引用（偶尔还叠加 §packed-refs 假同步，见 `silent-failure-triage` §4）。
- **对策**：用 `FETCH_HEAD`——`git log FETCH_HEAD -3`、`git diff origin/main FETCH_HEAD`；要写文件时 `git rev-parse FETCH_HEAD` 一定拿得到值。

- **验证于**：Windows 11 家庭中文版 10.0.26200.9457 · Git Bash 5.2.37 · git 2.53.0.windows.2 · 2026-09-17
- **复测条件（2026-09-17）**：本现象**取决于 `remote.<name>.fetch` 的 refspec**，不是无条件成立。① 默认 `+refs/heads/*:refs/remotes/origin/*` 下 `git fetch origin agent/writer/claim` 会**建出** `origin/agent/writer/claim`（输出行 `* [new branch]`），`git rev-parse` 退出码 0 ⇒ 不命中；② 收窄成 `+refs/heads/main:refs/remotes/origin/main` 后重跑同一条 fetch，输出只剩 `* branch … -> FETCH_HEAD`，`origin/agent/writer/claim` 解析失败 ⇒ 命中本节。两档下 `git rev-parse FETCH_HEAD` 都退出码 0；用显式 refspec（`refs/heads/<name>:refs/remotes/origin/<name>`）可事后补建跟踪引用。

## 6. 对象库损坏：别增量救，直接重 clone；旧判据本身是假阴性

- **现象**：读不到对象，而远端明明有这个提交。文案分两档（实测）：**对象文件不存在** → `fatal: git cat-file: could not get object info`；**文件在但字节损坏** → `error: inflate: data stream error (incorrect header check)` + `error: unable to unpack <sha> header`。两种下 `git cat-file -t <sha>` 退出码都是 **128**。（原文引的 `fatal: object <sha> is not a valid object (or nonexistent)` 本机没测到，别拿它当匹配串。）
- **对策**：重新 `git clone <url> <newdir>`；**旧目录改名留作 `<x>.corrupt-bak`，别直接删**（里面临时产物可能还有价值）。
- **判定（旧判据已作废）**：~~`git rev-list --objects <sha> | grep -ic missing` 为 0 才算修好~~ —— 实测在三种损坏下它**都返回 0**，包括 blob 真缺失、commit 完好但引用对象没了的情形，拿它当"修好了"会带着坏库继续干活。改用这两条，健康/损坏必然不同值：
  - `git rev-list --objects --missing=print <sha> | grep -c '^?'` → 健康 **0** / 缺一个 blob **1**（并把 `?<sha>` 打出来）；
  - `git fsck --no-progress` → 健康退出码 **0**、缺失退出码 **2**（输出 `missing blob <sha>`）。
  - 注意 `git rev-list --objects <sha>` **裸跑**在损坏时自己就退 **128**——它失败不代表 grep 拿到输入，所以"grep 没匹配"在这个管道里毫无信息量。
- **造现场的前置（实测）**：loose 对象文件属性是 `444`（`-r--r--r--`），直接覆盖会 `Permission denied`、退出码 **1**；要先 `chmod +w` 才写得进去。
- **验证于**：Windows 11 家庭中文版 10.0.26200.9457 · Git Bash 5.2.37 · git 2.53.0.windows.2 · 2026-09-17 首发
- **复测确认（2026-09-18，独立第二次重跑）**：新建小仓库使 blob 落成 loose（mode 444）→ 健康态 `^?` 计数 0、`fsck` 退 0；`chmod u+w` 后删掉该 blob → 旧判据 `grep -ic missing` **仍是 0**（假阴性复现）、裸 `rev-list` 退 **128**、`--missing=print` 的 `^?` 计数 **1**、`fsck` 退 **2** 并打印 `missing blob <sha>`。上面每个数字都被第二次跑到。

## 7. `force-with-lease` 报 `stale info`：先 fetch 再试

- **根因**：本地 `.git/refs/remotes/origin/*` 陈旧，而 `--force-with-lease` 正是拿它当"我以为的远端"。
- **对策**：`git fetch origin` 刷新跟踪引用后重试。要判断真实远端，读 `git rev-parse origin/main` 与 API 返回值对账，别凭印象。

- **验证于**：Windows 11 家庭中文版 10.0.26200.9457 · Git Bash 5.2.37 · git 2.53.0.windows.2 · 2026-09-17
- **实测取值**：两个 clone 指向同一个本地 bare 远端；A 再次 push 后，B 的本地 `origin/main` 停在旧值（`aac2dd9`）而远端真实为 `2a561b3`。B 执行 `git push --force-with-lease origin HEAD:refs/heads/main` → `! [rejected] HEAD -> main (stale info)`、退出码 **1**；`git fetch origin` 后本地 `origin/main` 刷新为远端值，重试 → `+ 2a561b3...aeebcf5 HEAD -> main (forced update)`、退出码 **0**，远端确实被覆盖。对账：`git rev-parse origin/main` 与远端 `rev-parse main` 值一致。

## 8. `git -c` 是顶层选项，写在子命令后面会退化

- **现象**：`git push -c http.proxy=… origin main` 只打印用法，看起来"什么也没发生"。
- **对策**：`git -c <opt>=<val> push …`（`-c` 必须在子命令之前）。实测 `git push -c http.proxy=… origin HEAD:refs/heads/<name>` → `error: unknown switch 'c'` + 打印 usage、退出码 **129**，远端确实没建出分支——它不是"什么也没发生"，是连命令都没解析完。把 `-c` 提到子命令之前重跑同一条 → 退出码 **0** 且分支建出（对策本身也被验证过，不是推出来的）。同族另一条 `git -C <dir>` 配 MSYS 形态路径（`<盘符>:/…` 与反斜杠绝对路径）连续 **5 次**全部退出码 **0** 并正确报出分支名，**`cannot change to` 在本机未证实，别按它预防**，只在别的 MSYS/git 组合上再查。
- **复测注意（实测）**：把 `http://127.0.0.1:<端口>` 这类含 `<` `>` 的占位符值不加引号写进 bash 命令行，`<` 会被当成输入重定向，报 `No such file or directory` 并**静默改掉整条命令**（与本节同族）；占位符值要么加引号，要么写成不带尖括号的串。

- **验证于**：Windows 11 家庭中文版 10.0.26200.9457 · Git Bash 5.2.37 · git 2.53.0.windows.2 · 2026-09-17

## 9. 暂存与收尾卫生

- **`git add -A` 会把工具落下的杂物一起提交**。API 查询常把 `*.json` 响应写进仓库目录，`-A` 一次把它们连同事前改动卷进同一个 commit（救回来要靠 `git reset --soft HEAD~1` + `git restore --staged .` + 删文件）。
  - 对策：显式列路径 `git add <文件1> <文件2>`；临时文件写到仓库外；提交后 `git show --stat HEAD` 扫一眼清单。
- **默认分支不是工作分支**：上一轮收尾常停在 `main`，直接开工就把提交落在本地 `main` 上。对策：动手前 `git branch --show-current`；已经提错了就 `git branch <新分支>`（保住提交）→ `git reset --hard origin/main`（本地 main 回退）→ 推新分支走 PR。
- **多人共享文件的追加位置**：两个人往同一文件**同一位置**追加必冲突；改成每人只写自己那一段（或分文件）则双向都干净。不联网也能预演：`git checkout -B tmp origin/main && git merge <A> && git merge <B>`，看完结果 `git merge --abort` 并删临时分支。

- **验证于**：Windows 11 家庭中文版 10.0.26200.9457 · Git Bash 5.2.37 · git 2.53.0.windows.2 · 2026-09-17
- **实测取值**：仓库里留一个工具写下的 `api-response.json`，`git add -A` 后 `git status --porcelain` 同时出现 `M  README.md` 与 `A  api-response.json`，该提交 `2 files changed`（只想提 1 个）；对策链路 `git reset --soft HEAD~1` → `git restore --staged .` → 删杂物 → `git add <单文件>` 后提交为 `1 file changed`、`git status --porcelain` 归 **0**。合并预演两档都复现：两分支在同一文件同一位置追加 → `CONFLICT (add/add): Merge conflict in shared.md`、`git merge` 退出码 **1**；各写各的文件 → 两次 `git merge` 均退出码 **0**、冲突文件 **0** 个。
- **同族两条（未复现/提醒）**：`git branch -D <临时分支>` 在临时分支**就是当前分支**时退出码 **1**（要先切走再删）；`git branch --show-current` 本机退出码 0、正确输出 `main`。

## 10. 批量删远端分支：查无 PR ≠ 垃圾

- **现象**：清理"看起来是模板产物"的分支时，差点删掉队友当天刚推的有效工作。
- **对策**：`GET /repos/<o>/<r>/branches?per_page=100` 全量列（**默认每页 30 条会漏**：实测某公共大仓库默认取数恰好回 **30** 条，`Link` 头里 `rel="next"`→page=2、`rel="last"`→page=175，而 `per_page=100` 回 100 条 ⇒ 同一请求两种形态差 **70** 条）→ 对每个候选查 `GET /pulls?state=all&head=<owner>:<branch>` 确认它合并过 → 再删 → 验证终态。删除用带重试的脚本并打印每个 HTTP 码，不要手点。
- **判定**：`head=` 那条查询是"这分支进没进过主干"的权威依据，**但它对"标签写错"和"真没有 PR"给出同一个形状**（实测：正确标签 → 200、命中 1 条并带 `merged_at`；随便编一个不存在的标签 → 同样 200、命中 **0** 条）。所以**空集之前必须先跑正控**——拿一个你确知有 PR 的分支跑同一条查询看它是否命中，命中了才信下一句的空集；否则一次拼写错误就会被读成"这分支没主，删掉安全"，方向正好反了。拿不准就不删，问一句比恢复便宜。
- **顺手一条**：`git push --delete` 不稳时改走 API 删 ref（`DELETE /repos/<o>/<r>/git/refs/heads/<name>`，204 即成功）。

- **状态**：**读侧已实测**（分页形状 + `head=` 查询的命中/空集两种返回，见下面验证于）。**写侧未复测**：真删远端分支不可逆、push/DELETE 权限只在维护者手里，本轮没有对任何真远端发过 `DELETE` 或 `git push --delete` ⇒ "204 即成功"与"带重试脚本 + 打印每个 HTTP 码"这两条仍按原结论保留，待有授权的回合再量。
- **验证于**：Windows 11 家庭中文版 10.0.26200.9457 · Git Bash 5.2.37 · Python 3.12.10 子进程调 System32 的 curl 8.21.0（`api.github.com` 只读 GET，未认证走直连）+ gh 2.97.0 · 2026-09-22
  （实测取值：默认 `?` 无参数 → rc=0 / 200 / 条数 30，`Link: <…branches?page=2>; rel="next", <…branches?page=175>; rel="last"`；`per_page=100` → 100 条；`per_page=100&page=2` → 100 条 ⇒ 该仓分支总数下界 200。`head=` 正控三条：`microsoft:benibenj/agents/…` → 200 命中 1 条（PR 337237，`merged=true`，`merged_at=2026-09-22T09:38:24Z`），另两条 closed+merged 的 `head.label` 同形状；负控：不存在的 head → 200 命中 0 条。样本只取公共仓库，未认证；无写操作。）

## 11. `-d` 传给 `git filter-branch` 的是它要 `rm -rf` 的临时目录：配 `-f` 时你的输入文件会先被删掉，而命令退出码 0

- **现象**：把一份清洗脚本的路径传给了 `-d`（`git filter-branch -f -d <脚本路径> …`）。命令**退出码 0**，stderr 只有一句 `WARNING: Ref 'refs/heads/main' is unchanged`，读起来像"没什么可改的空跑"。紧接着 `python <脚本路径>` 报 `can't open file … No such file or directory`，盘符绝对路径 / 相对路径 / MSYS 形态三种写法全都读不到——**被删的是输入，不是"没产出"**。代价：那份脚本未跟踪、git 里没有对象，永久丢失。
- **根因**：`-d <directory>` 声明的是 filter-branch **自己的临时目录**（`--tree-filter` 在里面 checkout），不是输出目录。本机 git 2.53.0.windows.2 的 `$(git --exec-path)/git-filter-branch` 里删它有三处：启动期 `rm -rf "$tempdir"`（**只在 `case "$force" in t)` 分支里**）、退出 trap `trap 'cd "$orig_dir"; rm -rf "$tempdir"' 0`（无条件）、收尾再一次。默认值 `tempdir=.git-rewrite`（相对当前工作目录）。**启动前的防护是 `test -d "$tempdir" && die "$tempdir already exists, please remove it"`——它只认目录**：路径是普通文件时防护根本不触发，`-f` 那条 `rm -rf` 照样把它删掉（`rm -rf` 对文件同样有效），随后 `mkdir -p "$tempdir/t"` 在同位置建出一个目录，退出时再连目录一起清掉。用法行只有 `[-d <directory>] [-f | --force]`，一个字没提"会被删除"，所以查 `-h` 挡不住这条；而且 `-h` 自己会先打印 `Proceeding with filter-branch...`，它不是纯读命令。
- **实测矩阵**（一次性 clone，2 笔提交，未跟踪哨兵；`--index-filter 'true'` 为空操作）：

  | 形态 | 退出码 | 哨兵终态 | 信号 |
  |---|---|---|---|
  | 不传 `-d` | 0 | — | filter 内 `pwd` 读出 `<仓库根>/.git-rewrite/t`；跑完 `.git-rewrite` 不存在 |
  | `-d <文件>`，**无** `-f` | **1** | **存活** | `mkdir: cannot create directory '<文件>': Not a directory` |
  | `-d <文件>` **+** `-f` | **0** | **消失** | 只有 `WARNING: Ref … is unchanged` |
  | `-d <文件>` + `-f`，且 filter 立即 `exit 7` | **7** | **仍然消失** | 改写尚未发生 ⇒ 删除在启动期，不在收尾 |
  | `-d <已存在的空目录>`，无 `-f` | **1** | 目录存活 | `<目录> already exists, please remove it` |
  | `-f -d <非空目录>`（内含一个在意的文件） | **0** | **目录连内容一起没了** | 同上，无任何"删除"字样 |
  | `-d <尚不存在的路径>`，无 `-f` | 0 | git 自建自清，可连续跑两次 | 无 |
- **对策**：
  - **优先不传 `-d`**：默认临时目录与仓库同盘、由 trap 自动清理，没有和输入重合的机会。
  - 确实要换盘（仓库在无执行权限盘 / 慢盘上）：**传一个尚不存在的路径，并且不要预先 `mkdir`**——实测预先建目录会让命令在没有任何改写的情况下退 **1**（`already exists`），这条直觉对策是错的。要可重复就别加 `-f`；加了 `-f` 就等于授权它删这个路径。
  - **前置检查（跑之前必过，逐条回显读数）**：
    ```bash
    ( TMP="<要传给 -d 的路径>"        # 不传 -d 时按默认填 .git-rewrite
      TOOL="<清洗脚本路径>"           # 必须在 TMP 之外
      [ -e "$TMP" ] && { echo "REFUSE: -d 目标已存在（文件会被删 / 目录报 already exists）"; exit 1; }
      [ -f "$TOOL" ] || { echo "REFUSE: 输入脚本不在场"; exit 1; }
      echo "OK tmp_absent=$TMP tool=$TOOL" ) ; echo "precheck_exit=$?"
    ```
    尖括号占位符**必须加引号**再写进 bash（见本文件 §8 末条），否则 `<` 变成输入重定向、整条命令被静默改掉。
  - **回滚路径**：被删的是**未跟踪文件**，git 里没有它的对象，`git checkout` / `git reset` 一律救不回 ⇒ 事前把工具脚本放在**仓库与工作目录之外**的固定工具目录，跑完立刻 `[ -f "$TOOL" ]; echo "still_there=$?"` 复核；已经吃掉的只能重新生成或从编辑器历史取，不要在 git 里找。判据：`-f` 用完后凡是 `-d` 给过的路径**一律当作已被删除**。
- **判定**：不背行号，跑版本无关的源码判据（命中数 >0 即确认 `-d` 是删除目标）：
  ```bash
  F="$(git --exec-path)/git-filter-branch"
  echo "F=$F exists=$([ -f "$F" ] && echo Y || echo N)"
  grep -c 'tempdir="\$OPTARG"\|rm -rf "\$tempdir"' "$F"
  ```
  本机实测输出 **4**（行号 168 赋值 / 223 启动期删除 / 237 trap 删除 / 657 收尾删除；默认值行 115 不匹配这个式子）。取路径**别用 `F=$(ls …)`**：本机 `ls` 带类型后缀，会把 `git-filter-branch` 打成 `git-filter-branch*`，随后 `grep: … No such file or directory`、退出码 **2**，而 `git --exec-path` 无此问题。安全复测照上面矩阵：一次性 clone + 一个哨兵**空文件**，跑完读 `[ -e <哨兵> ]`，**不要拿真脚本试**。
- **验证于**：Windows 11 家庭中文版 10.0.26200 · Git Bash 5.2.37（MSYS 3.6.6）· git 2.53.0.windows.2 · 2026-09-18 首发（真实代价：一份清洗脚本被 `-f -d` 吃掉），2026-09-19 一次性 clone 复测七态并更正根因与对策
- **与首发稿不一致处**：首发记为"收尾无条件 `rm -fr`"。复测更正为两支——启动期那次**只在 `-f` 下**执行（无 `-f` 时文件存活、命令退 1 并报 `Not a directory`），退出 trap 那次才是无条件；首发稿的对策"先 `mkdir -p <dir>` 再传 `-d`"实测**反而必退 1**，正确做法是传一个尚不存在的路径。

## 复用信号
"`git` 说成功了但分支不存在""提交里多了没改的文件""满屏 D""ref 怎么改都不动""这个提交没有父""命令退出码 0 但我的脚本不见了" → 先当作 `.git` 状态问题，按 §1/§2/§4 逐层验；凡是绕开正常流程改写 `.git` 的操作（§2、§11），不要用"再试一次"代替读状态。
