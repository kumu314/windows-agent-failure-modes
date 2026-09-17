---
name: shell-quoting-and-path-forms
description: Windows 上把文本和路径安全送进 shell 的失效模式。用 heredoc 写脚本、用 python -c 传长文本、往文件追加含反引号或中文标点的正文、Git Bash 里路径写法报错、taskkill/sc/reg 等原生命令传参、含空格目录名传给第三方 CLI 之前先读这条。触发词：heredoc、反斜杠被吞、反引号消失、命令替换、全角符号、cd /d、taskkill 无效、路径被拆开、8.3 短路径、/tmp 找不到、Glob 返回空、md5 对不上、哈希假不等。
agent_created: true
---

# Shell 转义与路径形态（Windows）

统一失效特征：**每一步的退出码都是 0，坏的是内容**。所以本族的判定全部要落到"读回来看字节"，不能看命令自述。

## 1. `python -c "…"` 与不带引号的 heredoc 会执行你传的正文

- **现象**：往 Markdown 追加一段含 `` `xxx` `` 的文本，命令成功、字符数也涨了，但所有反引号片段变成空。stderr 里躺着一行 `bash: somefile.json: command not found`——那是 shell 在**执行你的正文**。同族：`cat <<EOF`（定界符没加引号）里的反引号、`$(...)`、`${...}`；连中文引号 `“”` 都会被吃掉一部分。
- **根因**：双引号串内的 `` ` `` 和 `$()` 一律做命令替换，与"它是给 python 的参数还是给 cat 的正文"无关。
- **对策**：① 传长文本优先用编辑器的 Read+Edit / Write，压根不进 shell；② 必须 heredoc 时定界符加引号：`cat <<'EOF'`；③ 必须跑脚本就写成文件再 `python file.py`，别用 `-c` 拼几十行。
- **判定**：`grep -c '`' 目标文件`（或搜那段正文特有的关键词）。只看"追加了多少字符"必漏——字符数对、内容被替换过的情形最常见。

## 2. heredoc 再吞一层反斜杠

- **现象**：heredoc 里写 `\\theta` 想匹配 LaTeX 命令，落盘成 `\t heta`，正则全量匹配 0 条，而脚本一声不响。
- **根因**：heredoc 自身消化一层转义，正则需要的层数被减掉了。
- **对策**：能用 Write/Edit 就别用 heredoc；必须用时用 `chr(92)` 或原始字符串 `r"\\theta"` 构造，避免"数反斜杠"。
- **判定**：写完先跑一条 `python -c "print(repr(open(f,encoding='utf-8').read()[i:j]))"` 看落盘字面，再跑全量。

## 3. 全角符号破坏机器可读的数据契约

- **现象**：数据文件里是 `−2.5`（全角减号），下游正则 `-?\d+` 只认 ASCII `-`，匹配不到负号，把 `-2.5` 渲染成 `2.5`——**符号翻正**，肉眼看两版都对。
- **根因**：给机器解析的字段按排版习惯写了。
- **对策**：凡是被正则/解析器消费的字段只用 ASCII `- + . e ,`；排版层的全角替换放在最后一步、且在解析之后。
- **判定**：入库前 `grep -nP '[−×≤≥→""'']' 契约文件`，命中即打回。

## 4. MSYS 路径只有 bash 认，原生 exe 不认

- **现象**：`git apply --check /d/work/x.patch` → `error: can't open patch: No such file or directory`；`git commit-tree -F $(mktemp)` → `fatal: could not open '/tmp/tmp.XXXX'`。而 `ls /d/work/x.patch`、`cat /tmp/tmp.XXXX` 在 bash 里都好好存在。
- **根因**：`/d/`、`/tmp` 是 MSYS 挂载点，Git for Windows 是原生程序不参与映射；bash 内建与 coreutils 参与。同族：Git Bash 里 `curl -o /dev/null` 返回**退出码 23**（CURLE_WRITE_ERROR），把 `&&` 链断在身后。
- **对策**：交给原生程序的参数一律 Windows 形态（`D:/work/x.patch`）或仓库内相对路径（先 `cp /d/.../x.patch .git/x.patch` 再 `git apply --check .git/x.patch`）；只要 HTTP 码就 `curl -s -o <真实文件> -w "%{http_code}"`，别用 `/dev/null`。
- **判定**：`bash 侧看得见 + 原生程序报 No such file` = 就是这条，不要去查权限。

## 5. Git Bash 的 `/tmp` 与 Windows 版 Python 不是一个世界

- **现象**：bash 里 `curl -o /tmp/a.json` 成功，紧接着 `python -c "open('/tmp/a.json')"` → `FileNotFoundError`。反过来 Windows Python 往 `/tmp` 写，bash 也看不见。
- **根因**：MSYS `/tmp` 映射到某个私有目录，Windows 解释器把它按字面解析（常落到当前盘根的 `\tmp`）。
- **对策**：跨 bash↔Python 传递的中间文件一律写 **Windows 绝对路径**，且放在仓库外（`D:/tmp/…` 之类），避免被 `git add` 顺手收进来。
- **判定**：`python -c "import tempfile;print(tempfile.gettempdir())"` 与 `echo $TMPDIR / /tmp` 两边对一下即穿帮。

## 6. `cd /d/xxx` 与含空格路径

- **现象**：`cd /d D:\work` 在 Git Bash 里报 `cd: too many arguments`（`/d` 是 cmd.exe 的开关，不是 bash 的）；`cd "D:\新建 文件夹"` 或带中文的路径被拆成多段。
- **对策**：bash 用 `cd "D:/work"`（正斜杠 + 盘符 + 引号）；需要 cmd 语义就显式 `cmd /c`。任何含空格/中文的路径**永远加引号**。
- **判定**：同一命令换 `cd "D:/x"` 形式即成功，可确诊是形态问题而非目录不存在。

## 7. `//F` 与 `/Flag`：MSYS 会重写原生命令的开关

- **现象**：`taskkill //F //IM chrome.exe` 返回 0，进程还在；后续所有"我已经清理过了"的假设一起失效。`sc`、`reg`、`powercfg` 同理。
- **根因**：MSYS 的路径转换把 `//F` 当路径前缀处理成无效参数，而命令本身不报错。双斜杠是"防止被转换"的历史偏方，副作用是静默失败。
- **对策**：在 Git Bash 里调 Windows 原生命令用**单斜杠**并整体交给 `cmd /c "taskkill /F /IM chrome.exe"`，或直接改用 PowerShell；杀完必须 `tasklist | grep -i chrome` 复核。
- **判定**：`exit 0` + 进程仍在 = 命中本条；真报错反而是别的成因。

## 8. 含空格路径传给转发型 CLI：不报错，而是被拆成多个参数

- **现象**：把 `D:\some dir\plugin` 交给一个内部用 `spawn(..., { shell: true })` 转发参数的工具（包管理器、构建器、agent 自己的 CLI 壳），结果清单里凭空多出 `some`、`dir-plugin` 之类的垃圾依赖条目，命令没明确失败。
- **根因**：Windows 下 `shell: true` 不给含空格参数补引号，cmd 按空格切词。
- **对策**：① 首选消除空格——取 8.3 短路径再传：`cmd /c "for %I in (\"D:\some dir\") do @echo %~sI"` → `D:\SOME~1`；② 或把工作目录搬到无空格路径；③ 事后务必核对清单文件（`package.json` 等）被写进了什么，逐条撤销，注意别删**本来就存在的同名条目**。
- **判定**：报错里出现"路径的前半截"当目录名（`D:/some`）即 100% 命中。

## 9. 单一否定结果不要当结论

- **现象**：Glob 对含中文的长路径返回 `No files found`，于是判定"这个目录是空的"并开始重建；实际文件都在。
- **根因**：通配/编码层不稳，而"空结果"和"读不到"在工具输出里长得一样。
- **对策**：任何"0 命中"下结论前，换一条通道复核一次（`ls`、`Test-Path`、`find`）。同理：查询脚本 0 命中时，先证明**过滤器本身有效**（喂一个已知存在的串当对照组），再相信那个 0。
- **判定**：`ls "<同一目录>"` 有输出而 Glob 没有 → 是工具形态问题。

## 10. 用 `$(…)` 捕获内容再算哈希：必然"不一致"

- **现象**（本机实测）：核对"本地装的技能文件 == 远端 raw 的内容"，写成
  `V=$(curl -s <url>); printf '%s' "$V" | md5sum` → 与 `md5sum <本地文件>` **不等**，于是判"内容不一致"。
  同一份文件改成落盘再比，`diff` 空、字节数相同、md5 相同。
- **根因**：**命令替换会剥掉输出末尾的所有换行符**。文件的最后一个字节是 `\n`，捕获进变量后就没了，哈希自然不同。这是"看起来是内容差异、其实是取值形态差异"的典型。同一段里还有第二种假差异：那次 `curl` 根本没抓到东西（走代理与否决定），返回空串，`md5sum` 得到 **`d41d8cd98f00b204e9800998ecf8427e`**（空输入的 md5，一眼可认），却被读成"远端和本地不一样"。
- **对策**：**比对永远在文件上做**，别让内容过一遍 shell 变量：
  ```bash
  curl -sS -m 45 --proxy http://127.0.0.1:<端口> -o "D:/tmp/remote.md" "<url>"
  diff "D:/tmp/remote.md" "<本地文件>" && echo IDENTICAL
  ```
  非要用变量比，就把换行补回去再哈希：`printf '%s\n' "$V" | md5sum`（但仍不如 `diff` 直观，`diff` 还能指出差在哪一行）。
- **判定**：① 哈希等于 `d41d8cd98f00b204e9800998ecf8427e` ⇒ 是**空输入**，问题在抓取不在内容（按 `silent-failure-triage §2` 先证明取值通道有效）；② 两侧字节数只差 1 且文件尾是换行 ⇒ 命中本条；③ `wc -c` 两侧相同 + `diff` 为空，才算真一致。
