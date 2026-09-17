---
name: git-ref-plumbing-on-windows
description: Git for Windows / Git Bash 里 git 引用层与索引层的静默失效，以及 plumbing（write-tree/commit-tree/update-ref/read-tree）提交的安全用法。绕开正常 checkout、手搓提交、批量删分支、回滚之前读。触发词：update-ref 无效、unborn branch、checkout -b 回滚、commit-tree、write-tree、索引残留、文件莫名被删、packed-refs、worktree、force-with-lease、git add -A、误删分支。
agent_created: true
---

# Git 引用与索引（Windows）

本族的高频特征：**git 报 exit 0，坏的是 `.git` 里的状态**，而状态错误要到下一次操作才暴露，那时已经很难归因。凡动过 plumbing，就当自己欠一次验证。

## 1. MSYS 把带斜杠的 ref 吞掉（exit 0，ref 不存在）

- **现象**：`git update-ref refs/heads/agent/writer/sec1-sec2 <sha>` 或 `git checkout -B <含斜杠分支>` 返回 0，但 `.git/refs/heads/...` 不存在，HEAD 变成 unborn；objects、工作区文件写入都正常，**只有 ref 这一层回滚了**。全新 clone 也稳定复现。
- **根因**：MSYS 的路径转换把 `a/b/c` 形态的 ref 当文件系统路径处理。
- **对策（两个方向）**：
  - 文件系统直写：`mkdir -p .git/refs/heads/<上级目录> && printf '%s\n' <SHA> > .git/refs/heads/<上级>/<名字>`；
  - 或者干脆不在本地建 ref，**裸 SHA 推到远端建分支**：`git push origin <SHA>:refs/heads/<branch>`，之后 `git fetch && git reset --hard origin/<branch>` 对齐本地。
- **判定**：`git rev-parse <branch>` 能否解析出预期 SHA；解析不出而 ref 文件也不存在 = 命中。
- **注意**：裸 SHA 推送后本地没有 `origin/<branch>` 跟踪引用，后续引用一律用 `FETCH_HEAD`（见 §5）。

- **验证于**：Windows 11 家庭中文版 10.0.26200.9457 · Git Bash 5.2.37 · git 2.53.0.windows.2 · 2026-09-17
- **复测出入（2026-09-17）**：本机 **未复现**。`git update-ref refs/heads/agent/writer/sec1-sec2 <sha>` 退出码 **0**，`.git/refs/heads/agent/writer/sec1-sec2` 文件**存在**（41 字节），`git rev-parse` 解析出预期 SHA、退出码 **0**；`git checkout -B agent/writer/claim-x` 同样退出码 0 且 `git branch --show-current` 报出该名；`git symbolic-ref HEAD` 仍是 `refs/heads/main`、HEAD 可解析 ⇒ 无 unborn。全新 clone 与既有 clone 都试过。两版结论都保留：本节描述的失败若在别的 MSYS/git 组合上成立，请补上准确版本号。

## 2. `commit-tree` 之后索引不会自动复位

- **现象**：用 plumbing 造提交，"本次只改 2 个文件"的提交实际含 20 个文件，还以 `main` 为父（与另一条分支内容重复）。
- **根因**：`commit-tree` 只造对象，不动 HEAD 也不动索引；索引里还留着上一批已提交的改动，下一次 `git write-tree` 会把它们再打进去一次。
- **对策**：**每次 plumbing 提交完立刻复位索引**——`git read-tree <新HEAD>`（或 `git reset --mixed <新HEAD>`）。要精确控制内容就逐条 `update-index`：
  ```bash
  W=$(git rev-parse :path/to/a.md)          # 暂存区里那份 blob
  git read-tree main                        # 索引 = main 的树
  git update-index --add --cacheinfo 100644,$W,path/to/a.md
  git diff --cached --stat                  # 人肉确认只有你要的那几个
  SHA=$(git commit-tree "$(git write-tree)" -p main -F .git/msg.txt)
  ```
- **判定**：提交后 `git diff --stat <parent> <new>`，文件数远超预期即中招。

- **验证于**：Windows 11 家庭中文版 10.0.26200.9457 · Git Bash 5.2.37 · git 2.53.0.windows.2 · 2026-09-17
- **复测确认**：索引里先留 20 个文件的暂存改动、随后只 `git add` 2 个文件，`git write-tree` + `git commit-tree` 造出的提交实测为 `16 files changed, 18 insertions(+), 1 deletion(-)` —— 现象成立。`git reset --mixed HEAD` 复位索引有效（`git diff --cached --name-only` 由 1 归 0）。
- **复测出入（2026-09-17）**：`git read-tree <新HEAD>` 单独执行**不改变** `git diff --cached` 的结果——`commit-tree` 不动 HEAD，比较基准仍是旧提交；真正让索引“看起来干净”的是把分支指到新提交（`git update-ref refs/heads/<branch> <新SHA>`），此后 `git diff --cached` 自然为空，`read-tree` 成了幂等空操作。若场景里 HEAD 已先移动，本节原文的顺序才成立。

## 3. 绕开 checkout 切分支 → 上一分支的文件以 staged 形态残留

- **现象**：`read-tree`/`checkout-index` 切完分支，`git status` 里出现不属于当前分支的文件，且是已暂存状态。
- **对策**：凡是绕开正常 checkout 的手法，收尾固定 `git reset --hard <目标SHA>` + `git status` 双确认。
- **前提（重要）**：`reset --hard` 只在**工作树本来就该被丢弃**时用；有未提交改动时它会连你的改动一起抹掉。日常回滚优先 `git revert HEAD`（造一条反向提交，历史不断、不丢工作区）；`revert` 因冲突失败时先 `git stash` 再试，仍不行就从上一个提交里把文件内容读出来覆盖回去。
- **判定**：切完分支 `git status --porcelain` 必须为空，非空就当场处理，别带着脏状态继续干活。

- **验证于**：Windows 11 家庭中文版 10.0.26200.9457 · Git Bash 5.2.37 · git 2.53.0.windows.2 · 2026-09-17
- **实测取值**：在 bA（含 `newA.txt`）上执行 `git read-tree -m -u bB`，退出码 **0**、HEAD 仍在 bA，`git status --porcelain` 得到 `D  newA.txt`（1 行，已暂存形态），该文件已从工作区消失；`git read-tree --reset -u bB` 结果相同。对策 `git reset --hard bB` 后 `git status --porcelain` 为 **0** 行、`git rev-parse HEAD` 与 bB 相等。

## 4. worktree 会凭空"删除"文件

- **现象**：`git status` 突然满屏 `D`，但你没执行任何删除动作。
- **对策**：`git checkout -- .` 恢复即可；养成动手前 `git status --porcelain` 拍快照的习惯，异常先恢复再继续。
- **判定**：满屏 `D` 且自己没删过 → 就是它，不要去查是谁运行的清理脚本。

- **验证于**：Windows 11 家庭中文版 10.0.26200.9457 · Git Bash 5.2.37 · git 2.53.0.windows.2 · 2026-09-17
- **复测出入（2026-09-17，分两态）**：① **索引完好、只有工作区文件被外部删掉** → `git status --porcelain` 是 ` D`（未暂存），`git checkout -- .` 退出码 **0**、porcelain 归 0、文件回来 ⇒ 本节对策在这一态有效；② **索引也被清空**（实测用 `git read-tree --reset -u <空树>` 造出）→ porcelain 变 **16** 行 `D `（已暂存），此时 `git checkout -- .` 报 `error: pathspec '.' did not match any file(s) known to git` 且**退出码仍是 0**、什么都没恢复（本族最典型的“0 但没做成”），可用的是 `git checkout HEAD -- .` 与 `git read-tree --reset -u HEAD`，两者实测都把 porcelain 归 0、文件恢复。

## 5. 含斜杠分支 fetch 后没有 `origin/<name>`

- **现象**：`git fetch origin agent/writer/claim` 成功，但 `git log origin/agent/writer/claim` 报 `ambiguous argument`。
- **根因**：单分支 fetch 不生成对应的远程跟踪引用（偶尔还叠加 §packed-refs 假同步，见 `silent-failure-triage` §4）。
- **对策**：用 `FETCH_HEAD`——`git log FETCH_HEAD -3`、`git diff origin/main FETCH_HEAD`；要写文件时 `git rev-parse FETCH_HEAD` 一定拿得到值。

- **验证于**：Windows 11 家庭中文版 10.0.26200.9457 · Git Bash 5.2.37 · git 2.53.0.windows.2 · 2026-09-17
- **复测条件（2026-09-17）**：本现象**取决于 `remote.<name>.fetch` 的 refspec**，不是无条件成立。① 默认 `+refs/heads/*:refs/remotes/origin/*` 下 `git fetch origin agent/writer/claim` 会**建出** `origin/agent/writer/claim`（输出行 `* [new branch]`），`git rev-parse` 退出码 0 ⇒ 不命中；② 收窄成 `+refs/heads/main:refs/remotes/origin/main` 后重跑同一条 fetch，输出只剩 `* branch … -> FETCH_HEAD`，`origin/agent/writer/claim` 解析失败 ⇒ 命中本节。两档下 `git rev-parse FETCH_HEAD` 都退出码 0；用显式 refspec（`refs/heads/<name>:refs/remotes/origin/<name>`）可事后补建跟踪引用。

## 6. 对象库损坏：别增量救，直接重 clone

- **现象**：`git cat-file -t <sha>` → `fatal: object <sha> is not a valid object (or nonexistent)`，而远端明明有这个提交。
- **对策**：重新 `git clone <url> <newdir>`；**旧目录改名留作 `<x>.corrupt-bak`，别直接删**（里面临时产物可能还有价值）。
- **判定**：`git rev-list --objects <sha> | grep -ic missing` 为 0 才算修好，再换目录继续。

- **验证于**：Windows 11 家庭中文版 10.0.26200.9457 · Git Bash 5.2.37 · git 2.53.0.windows.2 · 2026-09-17
- **复测出入（2026-09-17，本节判定失效）**：`git rev-list --objects <sha> | grep -ic missing` 在三种损坏下**都返回 0**，无法区分修好与没修好——① commit 对象被改字节：`rev-list` 自己退出码 **128**、grep 拿不到输入；② commit 对象缺失：同样 128；③ commit 完好但它引用的 blob 缺失：`rev-list` 退出码 0 而不打印任何 `missing` 行 ⇒ grep 还是 0（假阴性）。可用的两条：`git rev-list --objects --missing=print <sha> | grep -c '^?'`（健康 **0** / blob 缺失 **1**，并打印 `?<sha>`）与 `git fsck --no-progress`（健康退出码 **0** / 缺失退出码 **2**，输出 `missing blob <sha>`）。
- **现象文案分档（实测）**：**对象文件不存在** → `fatal: git cat-file: could not get object info`；**文件在但字节损坏** → `error: inflate: data stream error (incorrect header check)` + `error: unable to unpack <sha> header`。两种下 `git cat-file -t <sha>` 退出码都是 **128**。本节原文引的 `fatal: object <sha> is not a valid object (or nonexistent)` 本机未测到。
- **造损坏场景的前置（实测）**：loose 对象文件属性是 `-r--r--r--`，直接覆盖会 `Permission denied`、退出码 **1**；要先 `chmod +w` 才写得进去。

## 7. `force-with-lease` 报 `stale info`：先 fetch 再试

- **根因**：本地 `.git/refs/remotes/origin/*` 陈旧，而 `--force-with-lease` 正是拿它当"我以为的远端"。
- **对策**：`git fetch origin` 刷新跟踪引用后重试。要判断真实远端，读 `git rev-parse origin/main` 与 API 返回值对账，别凭印象。

- **验证于**：Windows 11 家庭中文版 10.0.26200.9457 · Git Bash 5.2.37 · git 2.53.0.windows.2 · 2026-09-17
- **实测取值**：两个 clone 指向同一个本地 bare 远端；A 再次 push 后，B 的本地 `origin/main` 停在旧值（`aac2dd9`）而远端真实为 `2a561b3`。B 执行 `git push --force-with-lease origin HEAD:refs/heads/main` → `! [rejected] HEAD -> main (stale info)`、退出码 **1**；`git fetch origin` 后本地 `origin/main` 刷新为远端值，重试 → `+ 2a561b3...aeebcf5 HEAD -> main (forced update)`、退出码 **0**，远端确实被覆盖。对账：`git rev-parse origin/main` 与远端 `rev-parse main` 值一致。

## 8. `git -c` 是顶层选项，写在子命令后面会退化

- **现象**：`git push -c http.proxy=… origin main` 只打印用法，看起来"什么也没发生"。
- **对策**：`git -c <opt>=<val> push …`（`-c` 必须在子命令之前）。同族：`git -C <dir>` 配 MSYS 路径偶尔 `cannot change to`，改用 `cd` 进仓库再执行。

- **验证于**：Windows 11 家庭中文版 10.0.26200.9457 · Git Bash 5.2.37 · git 2.53.0.windows.2 · 2026-09-17
- **实测取值**：`git push -c http.proxy=http://127.0.0.1:<端口> origin HEAD:refs/heads/<name>` → `error: unknown switch 'c'`，随后打印 `usage: git push [<options>] …`，退出码 **129**，远端**确实没有**建出该分支；把 `-c` 提到子命令之前（`git -c <opt>=<val> push …`）退出码 **0** 且分支建出。
- **同族那条未复现（2026-09-17）**：`git -C <MSYS 形态路径>`（`<盘符>:/…`）连续 **5 次**全部退出码 **0** 并正确报出分支名，反斜杠绝对路径同样退出码 0——本节说的 `cannot change to` 需别的 MSYS/git 组合才会出现。
- **复测注意（实测）**：把 `http://127.0.0.1:<端口>` 这类含 `<` `>` 的值不加引号写进 bash 命令行，`<` 会被当成输入重定向，报 `No such file or directory` 并**静默改掉整条命令**（与本节同族）；占位符值要么加引号，要么写成不带尖括号的串。

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
- **对策**：`GET /repos/<o>/<r>/branches?per_page=100` 全量列（**默认每页 30 条会漏**）→ 对每个候选查 `GET /pulls?state=all&head=<owner>:<branch>` 确认它合并过 → 再删 → 验证终态。删除用带重试的脚本并打印每个 HTTP 码，不要手点。
- **判定**：`head=` 那条查询是"这分支进没进过主干"的权威依据；拿不准就不删，问一句比恢复便宜。
- **顺手一条**：`git push --delete` 不稳时改走 API 删 ref（`DELETE /repos/<o>/<r>/git/refs/heads/<name>`，204 即成功）。

- **状态**：复盘条目（本节复测必须对真远端发 GET/DELETE 并 push 删分支；push 权限只在维护者手里、且删除不可逆，按派活约定不在临时副本里伪造远端 API 场景，故本轮不落戳，保留原结论待有权限时补测）。

## 复用信号
"`git` 说成功了但分支不存在""提交里多了没改的文件""满屏 D""ref 怎么改都不动""这个提交没有父" → 先当作 `.git` 状态问题，按 §1/§2/§4 逐层验，不要用"再试一次"代替读状态。
