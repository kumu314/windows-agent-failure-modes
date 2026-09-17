---
name: shell-quoting-and-path-forms
description: Windows 上把文本和路径安全送进 shell 的失效模式。用 heredoc 写脚本、用 python -c 传长文本、往文件追加含反引号或中文标点的正文、Git Bash 里路径写法报错、taskkill/sc/reg 等原生命令传参、含空格目录名传给第三方 CLI 之前先读这条。触发词：heredoc、反斜杠被吞、反引号消失、命令替换、全角符号、cd /d、taskkill 无效、路径被拆开、8.3 短路径、/tmp 找不到、Glob 返回空、md5 对不上、哈希假不等、MAX_PATH、260 上限、长路径看不见。
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

## 11. 路径总长到 260 字符：一些工具照常成功，另一些连"文件存在"都看不见

- **现象**（本机实测，绝对路径长度逐字符可控）：把目录嵌深到**总长 260 字符以上**后，同一批工具分成两组——
  - **照常成功**：Node `fs.writeFileSync` / `fs.readFileSync`（300 字符路径退出码 **0**，读回 5 字节）、Git Bash 的 `cp` / `>` 重定向 / `wc -c`（300 字符退出码 **0**、报出字节数）。
  - **直接失败**：Python `open()` / `os.stat()`、PowerShell `Get-Content` 在 **260 起**一律 `FileNotFoundError(2, 'No such file or directory')` / `ItemNotFoundException`；`os.path.exists()` 返回 `False`；`cmd copy` 报 `系统找不到指定的路径`；`git add` 退出码 **128**（`error: open("…")`）。
  - **最容易读反的一档**：`cmd copy` 在**目标**路径越界时打印 `已复制         0 个文件。`、退出码 **1**——句式像成功、数字是 0；`pwsh New-Item -Directory` 到总长 250 就报 `完全限定文件名必须少于 260 个字符，并且目录名必须少于 248 个字符`。
  - 后果是本族最典型的坏结论：Node/bash 明明把文件写出来了，Python 一句 `False` 就让你判"没生成 / 目录是空的"，然后开始重建（与 `silent-failure-triage §2`、本文件 §9 同族）。
- **根因**：`LongPathsEnabled` 未开启时（本机实测值 `0`），不带 `\\?\` 前缀的 Win32 路径要过 MAX_PATH 检查，**实测可用上限是 259 字符**（260 起必失败）；**目录路径上限 247 字符**（248 起 `文件名或扩展名太长`）；**进程工作目录上限 258 字符**（259 起 `CreateProcess` 抛 `NotADirectoryError`）。官方的 260 / 248 是含结尾 NUL 的口径，所以能落地的最长值比它小 1。Node 的 libuv 与 MSYS coreutils 自己补前缀，因此不受这条限制——于是"甲建得出、乙看不见"。**相对路径不是绕法**：API 仍按 `cwd + 相对名` 拼成绝对路径再判，实测 cwd 长 242 时相对名 40 → 解析后 264 → 照样失败。
- **对策**：① 确实要越界时，命令里显式写 `\\?\<绝对路径>`——实测 Python、PowerShell 接受；`cmd` 报 `指定的路径无效。`、git 报 `fatal: Invalid path '//?/…'`（前缀会被 MSYS 改写成 `//?/`，所以 git 侧只能靠缩短路径）；② **`\\?\` 不能当进程工作目录**：`CreateProcess` 收到它会静默把 cwd 降级为 `<盘>:\Windows`、命令退出码 **0**，此后所有相对路径操作都落在系统目录里；③ 把长路径当**结构信号**——它通常说明中间产物该挪到浅目录；④ 临时救急可换 8.3 短名（`cmd /c "for %I in (…) do @echo %~sI"`，见本文件 §8），实测把 260 压到 133、300 压到 151、400 压到 196，且短名可被 Python 正常 `open()`。
- **判定**：同一文件过三条通道比对，出现分歧即命中本节：

  ```bash
  P="<盘>:\<深>\<深>\<文件>"                            # 绝对路径
  printf 'len=%s\n' "$(printf '%s' "$P" | wc -c)"       # ≥260 即落在本节范围
  python -c "import os,sys;print('py  ',os.path.exists(sys.argv[1]))" "$P"
  node   -e "console.log('node',require('fs').existsSync(process.argv[1]))" "$P"
  ```

  `node` 为 `true` 而 `py` 为 `False` ⇒ 文件真实存在、只是 Python 看不见 ⇒ 命中本条，**不要**据此重跑生成。需要贴边判定时按这三对阈值卡：259 成功 / 260 失败（文件）、247 / 248（目录）、258 / 259（工作目录）。
- **验证于**：Windows 11 家庭中文版 10.0.26200.9457 · Git Bash 5.2.37 · Git 2.53.0.windows.2 · Node v24.18.0 · Python 3.12.10 · PowerShell 5.1.26100.9444 · 2026-09-17

## 12. junction 的"是链接"每个工具答得不一样；删错的命令是 `del /f /s /q`

- **现象**（本机实测；样本均为 junction：`%USERPROFILE%\.trae-cn\skills` → `<工作区>\trae-data\skills`、`%USERPROFILE%\.agents\skills` → `<工作区>\agentskills`）：
  - PowerShell 5.1 `(Get-Item -Force <路径>).LinkType` → 这两个都是 `Junction`，`.Target` 是目标绝对路径；普通目录（`<工作区>\agentskills`）返回**空**。
  - Git Bash：`[ -L <路径> ]` 对 junction **恒为 no**（`-d` 为 yes）。
  - Python 3.12：`os.path.islink()` 同样 False；而 `pathlib.Path.is_junction()` 为 True。
  - Node 24：`lstat().isSymbolicLink()` **两种都出现过**——对上面两个 junction 是 true；对系统自带的 `%USERPROFILE%\AppData\Local\Application Data`（junction → `...\AppData\Local`）**是 false**。别把 `isSymbolicLink()` 当裁判。
- **根因**：junction 是 NTFS 重解析点（`fsutil reparsepoint query` 报 `Tag value: 0xa0000003`），Windows 对使用者透明；各工具链按自己的模型实现：MSYS `test -L` 与 Python `os.path.islink()` 只认另一种 tag，所以对 junction 一律说"不是链接"。**说"不是链接"的后果不是识别失败，是被当成普通目录去遍历和删除。**
- **对策**：
  - 识别一律读原始属性，别信包装函数：`$i=Get-Item -Force -LiteralPath <路径>; $i.LinkType`、`$i.Attributes -match 'ReparsePoint'`、`fsutil reparsepoint query <路径>`。
  - 要"看最终落到哪"就用会解析的：Node `fs.realpathSync()`、Python `Path.resolve()`；再拿 `os.path.islink()` / `is_junction()` 判断中间有没有链接层。
  - 删链接前先确认它**本身是**重解析点；删除只准 `rmdir "<链接>"`（或 `Remove-Item -LiteralPath <链接> -Recurse -Force`）。
  - **禁止**对链接用 `del /f /s /q "<链接>"`、`rmdir /s /q "<链接>"`、`rd /s /q "<链接>"`——这些会穿透进目标，把目标里的内容删掉，**退出码 0**，链接本身反而还在（实测：`del /f /s /q` 之后 `linkGone=false`，目标里的文件已消失）。这就是"删链接把别人数据删了"的真身。
  - 嵌套情形要当心：`%USERPROFILE%\.codex` 是 junction → `<工作区>\codex`；但 `.codex\skills` 不是重解析点（`fsutil` 报 `文件或目录不是重解析点`、`LinkType` 空），它是**穿过**上层 junction 落在目标里的真目录——此时 PowerShell 的 `[string] $i.Target` 还能给出一个看起来合法、实际不存在的前缀路径（它给的是 `C:\<工作区名>\codex\skills`，而该路径 `Test-Path` 为 false；Node `realpathSync` 给的是 `<工作区>\codex\skills`）。**LinkType 为空时就不要读 Target。**
  - git：把 junction 放进工作树，`core.symlinks=false` 管不了它，Git 会把目标整棵树当普通内容——实测 `git add link` 后 `git status` 是 `A  link/file0.txt`（目标里 4 个文件全部入库）；跨副本仓库里一个 junction 就能把几百 MB 拉进提交。
  - 通过 junction 进仓库目录（`cd link && git …`、`git -C "<junction>"`、Node `spawnSync(..., {cwd})`）都是**正常解析到真身**的，`rev-parse --show-toplevel` 返回真实路径，不必绕开。
- **判定**：① 识别：`fsutil reparsepoint query <路径>` 退出码 0 且输出含 `0xa0000003` ⇒ 是 junction（普通目录 ⇒ 退出码 1、`文件或目录不是重解析点`）；② `Get-Item -Force <路径>` 的 `LinkType` 等于 `Junction` ⇒ 是链接，`Target` 可读；③ 删除安全性，用一次抛弃型实测证明：`mklink /J tgt-lnk tgt` → 写入 `tgt\keep.txt` → `rmdir "tgt-lnk"` ⇒ 链接没了、`tgt\keep.txt` 还在；换 `del /f /s /q "tgt-lnk"` ⇒ 打印"删除文件 - …"、退出码 0、但 `tgt\keep.txt` 已不存在。**这两种结果的差别就是本节的判定标准。**
  - 附两条同族坑：`dir /al` 在"父目录没有重解析点"时退出码是 **1**、stderr 为 `File Not Found`——与"路径不存在"完全同形，别用它判断链接是否存在；PowerShell 5.1 的 `Remove-Item "<junction>"`（不带 `-Recurse`）删不掉链接，只报 `未能找到路径…` / `Cannot find path … because it does not exist`、退出码 1、链接还在（PowerShell 7 行为随版本有差异，本机未测）。
- **验证于**：Windows 11 家庭中文版 10.0.26200 · PowerShell 5.1.26100.9444 · Git Bash 5.2.37（git 2.53.0.windows.2）· Python 3.12.10 · Node v24.18.0 · 2026-09-17