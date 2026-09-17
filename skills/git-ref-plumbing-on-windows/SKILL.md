---
name: git-ref-plumbing-on-windows
description: Git for Windows / Git Bash 里 git 引用层与索引层的静默失效，以及 plumbing（write-tree/commit-tree/update-ref/read-tree）提交的安全用法。绕开正常 checkout、手搓提交、批量删分支、回滚之前读。触发词：update-ref 无效、unborn branch、checkout -b 回滚、commit-tree、write-tree、索引残留、文件莫名被删、packed-refs、worktree、force-with-lease、git add -A、误删分支。
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

## 3. 绕开 checkout 切分支 → 上一分支的文件以 staged 形态残留

- **现象**：`read-tree`/`checkout-index` 切完分支，`git status` 里出现不属于当前分支的文件，且是已暂存状态。
- **对策**：凡是绕开正常 checkout 的手法，收尾固定 `git reset --hard <目标SHA>` + `git status` 双确认。
- **前提（重要）**：`reset --hard` 只在**工作树本来就该被丢弃**时用；有未提交改动时它会连你的改动一起抹掉。日常回滚优先 `git revert HEAD`（造一条反向提交，历史不断、不丢工作区）；`revert` 因冲突失败时先 `git stash` 再试，仍不行就从上一个提交里把文件内容读出来覆盖回去。
- **判定**：切完分支 `git status --porcelain` 必须为空，非空就当场处理，别带着脏状态继续干活。

## 4. worktree 会凭空"删除"文件

- **现象**：`git status` 突然满屏 `D`，但你没执行任何删除动作。
- **对策**：`git checkout -- .` 恢复即可；养成动手前 `git status --porcelain` 拍快照的习惯，异常先恢复再继续。
- **判定**：满屏 `D` 且自己没删过 → 就是它，不要去查是谁运行的清理脚本。

## 5. 含斜杠分支 fetch 后没有 `origin/<name>`

- **现象**：`git fetch origin agent/writer/claim` 成功，但 `git log origin/agent/writer/claim` 报 `ambiguous argument`。
- **根因**：单分支 fetch 不生成对应的远程跟踪引用（偶尔还叠加 §packed-refs 假同步，见 `silent-failure-triage` §4）。
- **对策**：用 `FETCH_HEAD`——`git log FETCH_HEAD -3`、`git diff origin/main FETCH_HEAD`；要写文件时 `git rev-parse FETCH_HEAD` 一定拿得到值。

## 6. 对象库损坏：别增量救，直接重 clone

- **现象**：`git cat-file -t <sha>` → `fatal: object <sha> is not a valid object (or nonexistent)`，而远端明明有这个提交。
- **对策**：重新 `git clone <url> <newdir>`；**旧目录改名留作 `<x>.corrupt-bak`，别直接删**（里面临时产物可能还有价值）。
- **判定**：`git rev-list --objects <sha> | grep -ic missing` 为 0 才算修好，再换目录继续。

## 7. `force-with-lease` 报 `stale info`：先 fetch 再试

- **根因**：本地 `.git/refs/remotes/origin/*` 陈旧，而 `--force-with-lease` 正是拿它当"我以为的远端"。
- **对策**：`git fetch origin` 刷新跟踪引用后重试。要判断真实远端，读 `git rev-parse origin/main` 与 API 返回值对账，别凭印象。

## 8. `git -c` 是顶层选项，写在子命令后面会退化

- **现象**：`git push -c http.proxy=… origin main` 只打印用法，看起来"什么也没发生"。
- **对策**：`git -c <opt>=<val> push …`（`-c` 必须在子命令之前）。同族：`git -C <dir>` 配 MSYS 路径偶尔 `cannot change to`，改用 `cd` 进仓库再执行。

## 9. 暂存与收尾卫生

- **`git add -A` 会把工具落下的杂物一起提交**。API 查询常把 `*.json` 响应写进仓库目录，`-A` 一次把它们连同事前改动卷进同一个 commit（救回来要靠 `git reset --soft HEAD~1` + `git restore --staged .` + 删文件）。
  - 对策：显式列路径 `git add <文件1> <文件2>`；临时文件写到仓库外；提交后 `git show --stat HEAD` 扫一眼清单。
- **默认分支不是工作分支**：上一轮收尾常停在 `main`，直接开工就把提交落在本地 `main` 上。对策：动手前 `git branch --show-current`；已经提错了就 `git branch <新分支>`（保住提交）→ `git reset --hard origin/main`（本地 main 回退）→ 推新分支走 PR。
- **多人共享文件的追加位置**：两个人往同一文件**同一位置**追加必冲突；改成每人只写自己那一段（或分文件）则双向都干净。不联网也能预演：`git checkout -B tmp origin/main && git merge <A> && git merge <B>`，看完结果 `git merge --abort` 并删临时分支。

## 10. 批量删远端分支：查无 PR ≠ 垃圾

- **现象**：清理"看起来是模板产物"的分支时，差点删掉队友当天刚推的有效工作。
- **对策**：`GET /repos/<o>/<r>/branches?per_page=100` 全量列（**默认每页 30 条会漏**）→ 对每个候选查 `GET /pulls?state=all&head=<owner>:<branch>` 确认它合并过 → 再删 → 验证终态。删除用带重试的脚本并打印每个 HTTP 码，不要手点。
- **判定**：`head=` 那条查询是"这分支进没进过主干"的权威依据；拿不准就不删，问一句比恢复便宜。
- **顺手一条**：`git push --delete` 不稳时改走 API 删 ref（`DELETE /repos/<o>/<r>/git/refs/heads/<name>`，204 即成功）。

## 复用信号
"`git` 说成功了但分支不存在""提交里多了没改的文件""满屏 D""ref 怎么改都不动""这个提交没有父" → 先当作 `.git` 状态问题，按 §1/§2/§4 逐层验，不要用"再试一次"代替读状态。
