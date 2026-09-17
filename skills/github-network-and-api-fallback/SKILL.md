---
name: github-network-and-api-fallback
description: Windows 上 GitHub 网络链路的分层排障与 REST API 兜底通道。git 命令连不上但浏览器能用、push 退出码非 0 却一个字都不输出、gh 报 graphql EOF、凭证 401、"我推了你怎么看不到"、命令行长度爆掉、空仓库推不动之前读。触发词：502 CONNECT、schannel、Connection was reset、exit 128、proxy、代理、postBuffer、Out of memory、gh EOF、401、403、409、422、Contents API、base64、推不上去、连不上 github。
agent_created: true
---

# GitHub 网络分层排障 + API 兜底

一句话原则：**"连不上 GitHub"不是一个故障，是四类故障**——代理配置、TLS 栈、写通道、凭证。每一类有不同判据，混在一起重试就是烧轮次。

## 1. 命令行 git 不读 Windows 系统代理

- **现象**：浏览器能开 github.com，`gh` 能调 API，只有 `git push/fetch` 报 `Failed to connect to github.com port 443` / `CONNECT tunnel failed, response 502` / `schannel: server closed abruptly`。
- **根因**：WinHTTP/WinINet 的系统代理设置不影响 git；git 只认自己的 `http.proxy` 和 `HTTPS_PROXY` 环境变量，而后者在 Schannel 下**有时根本不生效**。
- **对策**：先查真实端口（很多人默认 7890，实际常不是），再一次性内联传入：
  ```powershell
  Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings" |
    Select-Object ProxyEnable, ProxyServer
  ```
  ```bash
  git -c http.proxy=http://127.0.0.1:<端口> push -u origin main
  ```
  端口猜错的表现为 `Could not connect to server`——那说明该端口上没程序监听，别硬试；用 `Get-NetTCPConnection -LocalPort <端口> -State Listen` 确认代理核心真的在跑（只有 helper 进程在 = 没在跑）。
  确实无代理时多为间歇性 reset，有界重试（≤5 次、每次间隔几秒）常能过。
- **判定 / 红线**：**不要为了省事写 `git config --global http.proxy`**。全局一旦设了，代理软件没开的每一次 git 操作都会去连那个死端口并超时，比直连失败更难排查（且这条配置在别人的机器上会跟着仓库走）。恢复办法只有 `--global --unset`，但那是改用户配置，属于应当避免的动作。
- **复测确认（2026-09-18）**：`Get-ItemProperty` 实测 `ProxyEnable=1`、`ProxyServer` 指向本机回环端口；同时四个常被猜的默认端口的 `Get-NetTCPConnection -State Listen` 计数**全为 0**——"默认端口猜错"当场实证：真端口只从注册表读，别猜（具体端口号按红线不入库）。系统代理开着的同时，`curl -s https://api.github.com/user` 仍直连拿到 401（见 §5），即命令行工具确实不读系统代理。
- **验证于**：Windows 11 家庭中文版 10.0.26200 · Git Bash 5.2.37 · PowerShell 5.1 · curl 8.18.0(Schannel) · 2026-09-18

## 2. 分层测，不要整体测：TCP 通 ≠ TLS 通 ≠ 写通道通

- **现象**（一手实测）：`github.com:443` 的 **TCP 握手 0.45 秒就通**，但任何 HTTPS 请求挂到超时（`curl` 返回 `http=000`、exit 28），`git push` exit 128；同一时刻 `api.github.com` 和 `codeload.github.com` **完全正常**，`gh api` 甚至能建成仓库。
- **误判代价**：看到"gh 能用"就断定"网络没问题、是 push 的命令写错了"，或者看到"端口能连"就去查防火墙——两边都错。
- **对策**：按层分开测，每层单独出结论：
  ```bash
  # L1 TCP
  python -c "import socket;s=socket.create_connection(('github.com',443),timeout=8);print('tcp ok');s.close()"
  # L2 TLS+HTTP，逐主机
  for h in github.com api.github.com codeload.github.com; do
    printf '%s ' "$h"; curl -s -m 12 -o /dev/null -w '%{http_code}\n' "https://$h"; done
  ```
  `L1 通 + L2 挂` = 该主机的 TLS 被中断，换代理或换协议通道，**别再改 git 参数**。`L2 通但 push 挂` = 问题在写通道，见 §5。
- **附带结论**：**`gh api` 通不代表 push 通**——它们走的是不同主机、不同协议路径。老规矩：先分层测量，再下诊断。
- **复测确认（2026-09-18）**：L1 实测 `github.com:443` TCP 握手 1.35 秒通；同一轮 L2 逐主机实测 **github.com=200 / api.github.com=200 / codeload.github.com=301，而 `raw.githubusercontent.com=000`（curl exit 28 超时）**——同一分钟四个主机三种结果，"L1 通 + 单主机 L2 挂"再次成立，且挂的是 §3 会提到的那台静态主机。
- **验证于**：Windows 11 家庭中文版 10.0.26200 · Git Bash 5.2.37 · python 3.12.10 · curl 8.18.0(Schannel) · 2026-09-18

## 3. 同一个 URL 在不同 TLS 栈下结论相反

- **现象**：PowerShell `Invoke-WebRequest` / `Invoke-RestMethod` 连 GitHub 或 npm 报"基础连接已经关闭"，而同一台机器上 `node -e "fetch(...)"` 一次成功；反过来 git(Schannel) 挂、curl(OpenSSL) 通的组合也真实存在。
- **根因**：Windows 上四套客户端各用各的 TLS 栈（Schannel / libcurl+OpenSSL / Node / .NET Http），受系统代理、证书库、TLS 版本策略的影响各不相同。
- **对策**：宣布"这个地址不可达"之前，**至少换一个栈验证**：
  ```bash
  node -e "fetch('https://raw.githubusercontent.com/<owner>/<repo>/main/README.md').then(r=>r.text()).then(t=>console.log(t.slice(0,200))).catch(e=>console.log('ERR:',e.message))"
  ```
  读仓库文件优先 `raw.githubusercontent.com`（纯静态，绕开 API 限流）；整包下载用 `https://codeload.github.com/<owner>/<repo>/zip/refs/heads/<branch>`（tag 换成 `refs/tags/<tag>`），比 `git clone` 更少受 git 通道问题牵连。
- **判定**：两个栈结果不一致时，**结论是"这个客户端不可达"，不是"网络不可达"**，直接换客户端而不是换网络。
- **复测确认（2026-09-18）**：同一 URL（`raw.githubusercontent.com/<owner>/<repo>/main/README.md`）同分钟三栈实测——**curl 8.18.0(Schannel) 超时（`http=000` / exit 28）、Node v24 `fetch` 成功（3653 字节）、PowerShell `Invoke-WebRequest` 成功（200 / 3653 字节）**。三栈两通一挂，"结论是'这个客户端不可达'"原样成立。注意本机 curl 也是 Schannel 后端、却与 git 的 Schannel 表现不同——栈按实测行为分，不按后端名字猜。
- **验证于**：Windows 11 家庭中文版 10.0.26200 · Git Bash 5.2.37 · curl 8.18.0(Schannel) · Node v24.18.0 · PowerShell 5.1 · 2026-09-18

## 4. `Out of memory, malloc failed (tried to allocate 524288000 bytes)`

- **现象**：小仓库 push 也 OOM，重试多少次都一样。
- **根因**：**全局 `http.postBuffer` 被设成 500MB**，git 试图一次性缓冲整个请求。调 `pack.windowMemory` / `pack.packSizeLimit` 完全无效——白耗好几轮。
- **对策**：判定 + 一次性覆盖，不改全局：
  ```bash
  git config --list --show-origin | grep -i postbuffer
  git -c http.proxy=http://127.0.0.1:<端口> -c http.postBuffer=1048576 push -u origin main
  ```
  **`gh` 会间接调用本地 git，同样中招**（`gh pr merge --delete-branch` 会触发本地 fetch/prune 而 OOM）。gh 没有 `-c`，用 git 的环境变量注入通道，内层 git 读得到：
  ```bash
  export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=http.postBuffer GIT_CONFIG_VALUE_0=1048576
  ```
- **判定**：报错里的字节数就是元凶——`524288000 ≈ 500MB`，和配置值对得上即确认。
- **复测确认（2026-09-18）**：`git config --list --show-origin | grep -i postbuffer` 在本机**直接命中全局 `.gitconfig` 的 `http.postbuffer=524288000`**——500MB 配置实锤在机，佐证"小仓库也 OOM"的机制；修复路径仍是 `-c http.postBuffer=1048576` 一次性覆盖，不动全局。
- **验证于**：Windows 11 家庭中文版 10.0.26200 · Git Bash 5.2.37 · git 2.53.0.windows.2 · 2026-09-18

## 5. push 彻底静默：exit 128，stdout/stderr 全空

- **现象**：`git push origin main`、`git push -u origin <b>`、带 `-c http.proxy` 的写法**全部** exit 128 且一个字都不输出，`Start-Process` 重定向捕获也是空；**而 fetch 仍然正常**。即"只读链路通、写链路死"。
- **误判**：因为没报错，看起来像"没执行"，于是无限重试、改 remote、rebase——全都没用，而且越动越危险。
- **对策**：先 30 秒定链路，再降级，且**降级后就固定在 API 通道**：
  ```bash
  curl -s -m 12 -o /dev/null -w '%{http_code}\n' https://api.github.com/user   # 401/403/200 都算通
  ```
  有 HTTP 码 = 网络与凭证都没问题，是 git 的 push 通道坏了 → 直接走 §6 的 Contents API。
- **止损线**：静默失败**重试超过 2 次就停**；不要 reset / rebase / 换 remote / `--force` 来"治好 push"——工作树没问题，动得越多风险越大。
- **复测确认（2026-09-18）**：`curl -s -m 12 -o /dev/null -w '%{http_code}' https://api.github.com/user` 实测返回 **401**（未带 token 的预期码）——"401/403/200 都算通"的 30 秒定链路判定可用；本机静默 push 失败场景本轮未重演（链路正常），止损线规则照旧。
- **验证于**：Windows 11 家庭中文版 10.0.26200 · Git Bash 5.2.37 · curl 8.18.0(Schannel) · 2026-09-18

## 6. Contents API 写文件：六个已知边界

```bash
gh api repos/<owner>/<repo>/contents/<path> --jq .sha          # ① 已存在的文件必须带 sha，否则 422
B64=$(base64 -w0 <本地文件>)                                    # ② 必须无换行；含 \n 判为非法 base64（macOS 用 | tr -d '\n'）
gh api --method PUT repos/<owner>/<repo>/contents/<path> \
  -f message="chore: update <path>" -f content="$B64" -f sha="<①>"   # ③ 返回体含新 commit.sha = 新分支 HEAD
```

- **④ 命令行长度**：base64 塞命令行，几十 KB 还行，上百 KB 就爆 → 先把 body 写成 JSON 文件再用 `--input body.json`。
- **⑤ 空仓库首推报 409** `Git Repository is empty`：blob→tree→commit→ref 的四步式在空仓库上必失败，**先 PUT 一个 `contents/README.md` 造出初始 commit** 再走其余步骤。
- **⑥ 一次 PUT 只能一个文件**：N 个文件 = N 个 commit，且本地 HEAD 立刻落后远端 → 走 API 之后本地与远端**必然分叉**；后续要正常协作就重新 clone（别指望 `reset --mixed origin/main` 在这种环境下落盘）。
- **验证（缺一不可，别只看"200"）**：
  ```bash
  gh api repos/<owner>/<repo>/branches/main --jq .commit.sha          # a) 远端 HEAD == 返回的 commit.sha
  gh api repos/<owner>/<repo>/contents/<path> --jq .content | tr -d '\n' | base64 -d | sha256sum
  sha256sum <本地文件>                                                # b) 两个 sha256 相同才算推成功
  ```
  比"文件大小/行数"会漏掉内容被截断；字节级哈希是唯一硬证据。
- **收尾**：立刻把真实远端 SHA 记进项目记录，否则下一轮会误判"推没推上去"。
- **复测确认（2026-09-18 · 只读）**：`gh api repos/<owner>/<repo>/branches/main --jq .commit.sha` 一次取值成功（并用作 §8 对账基准）；PUT 写入路径本轮未重演（写目标仓库属对外动作，由仓库维护者执行，agent 不动），边界 ①②③⑤⑥ 维持原文。
- **验证于**：Windows 11 家庭中文版 10.0.26200 · Git Bash 5.2.37 · gh 2.97.0 · 2026-09-18

## 7. 凭证侧的三个静默坑

- **从 `git credential fill` 取出的 token 带 `\r\n`** → 每个 `Authorization: token <...>` 请求 **401**。必须 `| tr -d '\r\n'`。取 token：
  ```bash
  export GH_TOKEN=$(printf "protocol=https\nhost=github.com\n\n" | git credential fill | grep '^password=' | cut -d= -f2 | tr -d '\r\n')
  ```
- **`gh` 突然要求 `gh auth login`、`gh auth status` 说没有登录任何 host、`~/.config/gh/` 不存在** = gh 的登录态丢了，**但 GCM 里的凭据通常还在**（`git credential fill` 仍能拿到）。此时别去跑交互式的 `gh auth login`（自动化环境里跑不完），直接切 curl + token，或 `export GH_TOKEN=...` 让 gh 复用。
- **403 的响应体里通常写着答案**（例：`Upgrade to GitHub Pro or make this repository public to enable this feature.` = 该功能私有库不开放）。只看状态码就重试，等于把一句话能定位的问题重跑十遍。同理，`422` 十有八九是 **SHA 少写/多写一位**——SHA 永远动态取（`git rev-parse HEAD` 或上一步 API 返回值），禁止手敲短 SHA 拼长。
- **"推成功 ≠ 可访问"**：交付物的在线链接在仓库仍是 private 时对外是 404。要么改可见性（这是对外的动作，先取得同意），要么别声称链接可用。
- **复测环境差异（2026-09-18）**：本机 `gh auth status` 完好（keyring 存储、token 含 `repo` scope），"登录态丢失、`~/.config/gh/` 不存在"的场景**未复现**——本轮无 401 循环现场，`tr -d '\r\n'` 路径也无需触发；原结论保留，遇到真实 401 时按本节排查。
- **验证于**：Windows 11 家庭中文版 10.0.26200 · Git Bash 5.2.37 · gh 2.97.0 · 2026-09-18

## 8. 逐对象核对"远端 == 本地"：三处会自己造出假警报的地方

- **现象**（本机实测，同一分钟内连犯两次）：推完之后做对象级核对，`git rev-parse HEAD^{tree}` 得 `4eb2a99…`，`gh api repos/<owner>/<repo>/git/trees/HEAD --jq .sha` 得 `6038fd2…` → 判"远端树和本地不一样"，准备重推。第二次改用 `git ls-tree -r` 与 API 的 `.tree[]` 逐行比，又报满屏差异。两次都是**假警报**，而且都长得像"发现了真问题"。
- **根因 / 对策**：三个互相独立的坑叠在一起：
  1. **`/git/trees/{ref}` 的 `.sha` 回显的是你传入的 ref 所解析到的对象，不是它返回的那棵树的 SHA。** 传 `HEAD`（或 commit SHA）→ `.sha` 就是 **commit SHA**；要 tree SHA 必须传 `HEAD^{tree}`（URL 里写成 `HEAD%5E%7Btree%7D`），或者改读 `commits/{ref}` 的 `.commit.tree.sha`。
  2. **条目数天生不等**：`git ls-tree -r` 只列 blob，API `?recursive=1` 把**目录级的 tree 条目**也列出来。13 个文件 + 11 个目录条目 = API 给 24 行，于是"远端比本地多 11 条"纯属口径差。对齐方式二选一：`git ls-tree -r -t` ↔ `.tree[]` 全量；`git ls-tree -r` ↔ `.tree[] | select(.type=="blob")`。
  3. **分隔符不同**：`git ls-tree` 的行格式是 `mode SP type SP sha TAB path`——SHA 与路径之间是 **TAB**，而 `--jq` 拼出来的是空格 → 原始 `diff` 永远不等。比对前先 `tr '\t' ' '`。
- **对策（一条命令同时取两侧，让 diff 自己说话）**：
  ```bash
  R=<owner>/<repo>
  gh api "repos/$R/git/trees/HEAD%5E%7Btree%7D?recursive=1" \
    --jq '.tree[] | "\(.mode) \(.type) \(.sha) \(.path)"' > D:/tmp_api.txt
  git ls-tree -r -t HEAD | tr '\t' ' ' > D:/tmp_git.txt
  diff D:/tmp_git.txt D:/tmp_api.txt && echo IDENTICAL
  ```
  两侧都取 **full SHA**，别拿 7 位短 SHA 参与比对。
- **判定**：① 上面 `diff` 为空且本地 `git cat-file -t <远端返回的 commit.sha>` 不报错 = 真一致；② 报"少文件"之前先读返回体的 **`.truncated`**——大仓库的 `recursive=1` 会截断，`truncated: true` 时"远端少了几条"是**接口没返回**，不是仓库真缺；③ 只有当换掉 `tr '\t' ' '` 之后 diff 才变红，才说明确实是内容差异而不是分隔符。
- **附带一条同族**：这台机器的 Git Bash 里**没有外部 `jq`**。把取值写成 `echo ".sha : $(curl -s … | jq -r .sha)"` 时，输出是**空串**而 `$?` 是 **0**（实测：改成 `v=$(jq …)` 的赋值形式才露出 `127`），于是 5 个字段全空，看起来完全像"API 没返回这些字段"。改用 `gh api --jq`（自带表达式引擎、不依赖外部 `jq`）后一次就取到了值。泛化规则见 `silent-failure-triage §2`。
- **复测确认（2026-09-18）**：三个坑全部当场复现——① `gh api repos/<owner>/<repo>/git/trees/HEAD --jq .sha` 回显的是 **commit SHA**、传 `HEAD^{tree}` 才得 tree SHA，两者实测不同值；② 口径差实测 **16（blob-only）vs 28（含目录条目）**、返回体 `.truncated=false`；③ 未做 `tr '\t' ' '` 时原始 `diff` 报 **28 行全红**，同一基准加上 `tr` 后 `diff` 为 **IDENTICAL**。外部 `jq` 缺失同样复现（`which jq` 无输出）。
- **复测的元教训（2026-09-18）**：第一次对账拿**本地 HEAD（领先远端 2 个未推提交）**去比**远端 HEAD**，得到 28 行"差异"——方向对、基准错，那是**真实分歧**不是格式坑。**对账第一步是把两侧钉到同一个 commit**：先 `gh api .../branches/main --jq .commit.sha` 取远端基准、确认本地 `git cat-file -t <sha>` 存在再开比；分叉状态下任何"不一致"结论都无效。
- **验证于**：Windows 11 家庭中文版 10.0.26200 · Git Bash 5.2.37 · git 2.53.0.windows.2 · gh 2.97.0 · 2026-09-18

## 复用信号

- "浏览器/gh 能用只有 git 不行" → §1；"端口能连但请求挂" → §2；"这个客户端说不通行另一个说不通" → §3；"OOM 的字节数像配置的默认值" → §4；"push 不报错也不成功" → §5 → §6；"每次都是 401/422" → §7；"核对时两个 SHA 对不上 / 条数差一截" → §8。
