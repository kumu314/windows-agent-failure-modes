---
name: shell-quoting-and-path-forms
description: Windows 上把文本和路径安全送进 shell 的失效模式。用 heredoc 写脚本、用 python -c 传长文本、往文件追加含反引号或中文标点的正文、Git Bash 里路径写法报错、taskkill/sc/reg 等原生命令传参、含空格目录名传给第三方 CLI 之前先读这条。触发词：heredoc、反斜杠被吞、反引号消失、命令替换、全角符号、cd /d、taskkill 无效、路径被拆开、8.3 短路径、/tmp 找不到、Glob 返回空、md5 对不上、MAX_PATH、长路径看不见、属性不存在、全判否、0 命中是假的。
agent_created: true
---

# Shell 转义与路径形态（Windows）

统一失效特征：**每一步的退出码都是 0，坏的是内容**。所以本族的判定全部要落到"读回来看字节"，不能看命令自述。

## 1. `python -c "…"` 与不带引号的 heredoc 会执行你传的正文

- **现象**：往 Markdown 追加一段含 `` `xxx` `` 的文本，命令成功、字符数也涨了，但所有反引号片段变成空。stderr 里躺着一行 `bash: somefile.json: command not found`——那是 shell 在**执行你的正文**。同族：`cat <<EOF`（定界符没加引号）里的反引号、`$(...)`、`${...}`；连中文引号 `“”` 都会被吃掉一部分。
- **根因**：双引号串内的 `` ` `` 和 `$()` 一律做命令替换，与"它是给 python 的参数还是给 cat 的正文"无关。
- **对策**：① 传长文本优先用编辑器的 Read+Edit / Write，压根不进 shell；② 必须 heredoc 时定界符加引号：`cat <<'EOF'`；③ 必须跑脚本就写成文件再 `python file.py`，别用 `-c` 拼几十行。
- **判定**：`grep -c '`' 目标文件`（或搜那段正文特有的关键词）。只看"追加了多少字符"必漏——字符数对、内容被替换过的情形最常见。

- **验证于**：Windows 11 家庭中文版 10.0.26200.9457（zh-CN）· Git Bash 5.2.37(1)-release(x86_64-pc-msys) · Python 3.12.10 · 2026-09-21
  （temp 内活测：同一行正文先喂 `cat <<EOF`（定界符无引号）再喂 `cat <<'EOF'`。无引号版落盘 86 B、反引号数 **0**、
  `whoami` 的位置变成账号名、`$(id -u)` 的位置变成 uid；有引号版 90 B、反引号数 2。
  附带一条判据修正：这次 stderr **是空的**（被执行的 `whoami`、`id -u` 都成功了），
  所以"去 stderr 找 `command not found`"只是充分不必要——真正可靠的是数目标字符（反引号数 2 → 0）。）
- **复测出入（2026-09-21，同一批）**：`“”` 这一支**未复现**——`“引用”` 在无引号定界符的 heredoc 里原样落盘，两个码点都在。
  能确定被吃掉的是 `` ` ``、`$()`、`${}`；"中文引号也会被吃"按未验证处理，若在特定 shell/版本上成立请补版本号。

## 2. heredoc 再吞一层反斜杠

- **现象**：heredoc 里写 `\\theta` 想匹配 LaTeX 命令，落盘成 `\t heta`，正则全量匹配 0 条，而脚本一声不响。
- **根因**：heredoc 自身消化一层转义，正则需要的层数被减掉了。
- **对策**：能用 Write/Edit 就别用 heredoc；必须用时用 `chr(92)` 或原始字符串 `r"\\theta"` 构造，避免"数反斜杠"。
- **判定**：写完先跑一条 `python -c "print(repr(open(f,encoding='utf-8').read()[i:j]))"` 看落盘字面，再跑全量。

- **验证于**：Windows 11 家庭中文版 10.0.26200.9457 · Git Bash 5.2.37 · Python 3.12.10 · 2026-09-21
  （活测：源文本同为 `pat = \\theta`，`cat <<EOF` 落盘 `repr()` = `'pat = \\theta'`（反斜杠数 **1**），
  `cat <<'EOF'` 落盘 `'pat = \\\\theta'`（数 **2**）⇒ 无引号定界符恰好吃掉一层。）
- **判据收紧（2026-09-21）**：**定界符加引号不等于保险**。本轮用 `python - <<'PY'` 传一段含 `'\\\\?\\'`（扩展长度前缀）的脚本，
  引号加了仍少一层，落盘成 `'\\?\'` → `SyntaxError: unterminated string literal`，报错指向的行还不是我以为是的那一行。
  传参链上还有别的层在吃反斜杠（工具层 / 命令行层），本机无法把它们拆开。
  ⇒ 对策 ① 的适用面比原文更宽：**正文里只要含反斜杠，就不要过 shell，直接 Write 成文件**；
  非要传就用 `chr(92)` 拼（本轮最后就是靠 `chr(92)` 一次过的）。

## 3. 全角符号破坏机器可读的数据契约

- **现象**：数据文件里是 `−2.5`（全角减号），下游正则 `-?\d+` 只认 ASCII `-`，匹配不到负号，把 `-2.5` 渲染成 `2.5`——**符号翻正**，肉眼看两版都对。
- **根因**：给机器解析的字段按排版习惯写了。
- **对策**：凡是被正则/解析器消费的字段只用 ASCII `- + . e ,`；排版层的全角替换放在最后一步、且在解析之后。
- **判定**：入库前 `grep -nP '[−×≤≥→""'']' 契约文件`，命中即打回。

- **验证于**：Windows 11 家庭中文版 10.0.26200.9457 · Git Bash 5.2.37 · GNU grep 3.0 · Python 3.12.10 · 2026-09-21
  （活测：temp TSV 两行，值分别是全角 `−2.5`（首字符 U+2212）与 ASCII `-2.5`（U+002D）。
  `re.findall(r'-?\d+\.?\d*', v)` 取到 `['2.5']` 与 `['-2.5']` ⇒ 全角那行**符号翻正**，且长度、小数位都对，肉眼看不出。
  判定命令两条都有效（不必退回逐字符 `-F`）：`grep -nP '[−×≤≥→“”‘’]'` 与 `grep -nE '[−×≤≥]'` 在同一 zh-CN 环境下都命中第 1 行、rc=0。）

## 4. MSYS 路径只有 bash 认，原生 exe 不认

- **现象**：`git apply --check /d/work/x.patch` → `error: can't open patch: No such file or directory`；`git commit-tree -F $(mktemp)` → `fatal: could not open '/tmp/tmp.XXXX'`。而 `ls /d/work/x.patch`、`cat /tmp/tmp.XXXX` 在 bash 里都好好存在。
- **根因**：`/d/`、`/tmp` 是 MSYS 挂载点，Git for Windows 是原生程序不参与映射；bash 内建与 coreutils 参与。同族：Git Bash 里 `curl -o /dev/null` 返回**退出码 23**（CURLE_WRITE_ERROR），把 `&&` 链断在身后。
- **对策**：交给原生程序的参数一律 Windows 形态（`D:/work/x.patch`）或仓库内相对路径（先 `cp /d/.../x.patch .git/x.patch` 再 `git apply --check .git/x.patch`）；只要 HTTP 码就 `curl -s -o <真实文件> -w "%{http_code}"`，别用 `/dev/null`。
- **判定**：`bash 侧看得见 + 原生程序报 No such file` = 就是这条，不要去查权限。

- **验证于**：Windows 11 家庭中文版 10.0.26200.9457 · Git Bash 5.2.37(1)-release(x86_64-pc-msys) · git 2.53.0.windows.2 · curl 8.18.0 · Node v24.18.0 · Python 3.12.10 · 2026-09-21
- **复测出入（2026-09-21，原文三条读数全部未复现；temp 新建仓库跑，无副作用）**：
  ① `git apply --check <MSYS 形态绝对路径>` **rc=0**——同一份补丁的 Windows 形态、仓库内相对、`./` 三种写法也全 rc=0；
  ② `git commit-tree -F /tmp/<消息文件>` **正常产出提交对象**，那句 `fatal: could not open '/tmp/tmp.XXXX'` 没有出现；
  ③ `curl -o /dev/null` 在 https 直连、加 `-sS`、加 `-w '%{http_code}'`、改 `-o NUL`、以及放进 `&&` 链五种给法下**一律 rc=0**，
  退出码 23 未出现，`&&` 后半段照常执行（对照组：不存在的 host rc=6、`--fail` 打 404 rc=22，说明命令本身跑得动）。
- **真正的边界在"哪一层参与转换"**：`cygpath -w /d` = `<盘>:\`、`cygpath -w /tmp` = 挂载表里那条真实目录，
  转换发生在 **bash 交给子进程的 argv 上**，所以原生 exe 收到的是已经换算过的 Windows 形态（实测 node、python 拿 argv 里的 `/d/...` 都能读到文件）。
  于是原文那句要按两支改写：**(a) 只改 argv，不改脚本正文**——同一条路径写进 `-c "…"` 里就没有转换，Python 把 `/tmp/x` 按字面解析成 `<盘>:\tmp\x`（这一支就是 §5）；
  **(b) 复合路径只换前半**——实测把 `/tmp/../d/work/x.patch` 交给 `git apply --check`，git 收到的是 `<盘>:/<TMP挂载点>/../d/work/x.patch` 这种半中半西的形态，rc=**128** `error: can't open patch`。
- **判据改写后仍成立的那一句**：路径写法出事时，**同一份内容换两三种写法各跑一次**（MSYS 形态 / Windows 形态 / 仓库内相对），
  用退出码差异定位是哪一层在改写法；不要去查权限，也不要把"某条路径失败"直接写成"原生程序不认 MSYS 路径"。
  本轮适用版本记为 Git Bash 5.2.37 + git 2.53 + curl 8.18；更早版本若真报 `can't open patch`，属另一档行为，补版本号后再并存。

## 5. Git Bash 的 `/tmp` 与 Windows 版 Python 不是一个世界

- **现象**：bash 里 `curl -o /tmp/a.json` 成功，紧接着 `python -c "open('/tmp/a.json')"` → `FileNotFoundError`。反过来 Windows Python 往 `/tmp` 写，bash 也看不见。
- **根因**：MSYS `/tmp` 映射到某个私有目录，Windows 解释器把它按字面解析（常落到当前盘根的 `\tmp`）。
- **对策**：跨 bash↔Python 传递的中间文件一律写 **Windows 绝对路径**，且放在仓库外（`D:/tmp/…` 之类），避免被 `git add` 顺手收进来。
- **判定**：`python -c "import tempfile;print(tempfile.gettempdir())"` 与 `echo $TMPDIR / /tmp` 两边对一下即穿帮。

- **验证于**：Windows 11 家庭中文版 10.0.26200.9457 · Git Bash 5.2.37 · Python 3.12.10 · 2026-09-21
  （活测：bash 里 `printf X > /tmp/probe.txt` 成功且 `ls` 得到；同一时刻 Python
  `os.path.exists('/tmp/probe.txt')` = **False**、`open()` 抛 `FileNotFoundError`；
  `os.path.abspath('/tmp')` = `<盘>:\tmp`，而挂载表那行写的是 `/tmp` → `$TMP` 指的那块真实目录（本机不是 `<盘>:\tmp`）。
  反向也对：Python 往 `tempfile.gettempdir()` 写的文件，bash 用同一个 Windows 绝对路径 `ls` 得到。
  判定命令有效：`gettempdir()` 与 `/tmp` 两个读数不同即穿帮，本轮 = `D` 盘某真实目录 vs `<盘>:\tmp`，一眼分家。）

## 6. `cd /d/xxx` 与含空格路径

- **现象**：`cd /d D:\work` 在 Git Bash 里报 `cd: too many arguments`（`/d` 是 cmd.exe 的开关，不是 bash 的）；`cd "D:\新建 文件夹"` 或带中文的路径被拆成多段。
- **对策**：bash 用 `cd "D:/work"`（正斜杠 + 盘符 + 引号）；需要 cmd 语义就显式 `cmd /c`。任何含空格/中文的路径**永远加引号**。
- **判定**：同一命令换 `cd "D:/x"` 形式即成功，可确诊是形态问题而非目录不存在。

- **验证于**：Windows 11 家庭中文版 10.0.26200.9457 · Git Bash 5.2.37 · 2026-09-21
  （temp 内活测四条：`cd /d <路径>` → `bash: line 1: cd: too many arguments`、rc=1；
  `cd "<盘>:/work"` → 成功（`pwd` 回显成 `/d/work` 形态，这本身是 §4 那支 argv 转换的另一面）；
  `cd <含空格目录>`（不加引号）→ 报的也是 `too many arguments`，**不是** `No such file or directory`——
  这条区分值钱：见到 `too many arguments` 就说明是切词/开关问题，目录根本没被当成一个参数送去；
  `cd "<含空格 + 中文的目录>"` → 成功。）

## 7. `//F` 与 `/Flag`：MSYS 会重写原生命令的开关

- **现象**：`taskkill //F //IM chrome.exe` 返回 0，进程还在；后续所有"我已经清理过了"的假设一起失效。`sc`、`reg`、`powercfg` 同理。
- **根因**：MSYS 的路径转换把 `//F` 当路径前缀处理成无效参数，而命令本身不报错。双斜杠是"防止被转换"的历史偏方，副作用是静默失败。
- **对策**：在 Git Bash 里调 Windows 原生命令用**单斜杠**并整体交给 `cmd /c "taskkill /F /IM chrome.exe"`，或直接改用 PowerShell；杀完必须 `tasklist | grep -i chrome` 复核。
- **判定**：`exit 0` + 进程仍在 = 命中本条；真报错反而是别的成因。
- **验证于**：Windows 11 家庭中文版 10.0.26200 · Git Bash 5.2.37 · git 2.53.0.windows.2 · cmd 10.0 · 2026-09-18
- **复测出入（2026-09-18 · Git Bash 5.2.37 / git 2.53.0.windows.2，与原文方向相反）**：本机实测（完整矩阵见 chromium-cdp-on-windows §6 同批注记；全部用不存在的进程名或本实例 PID，无副作用）——`taskkill //F //IM <名>` 的 `//F` **被正确转成 `/F` 传给 taskkill**（报"没有找到进程"而非参数错误），`taskkill //F //PID <本实例 PID>` 退出码 0 且进程真的终止（`curl /json/version` 立即失联）；反过来 `taskkill /F /IM <名>` 报 `错误: 无效参数/选项 - 'F:/'`（`/F` 被当路径转成 `F:/`）。`cmd /c` 包装同理：`cmd /c "echo hello"` 里的 `/c` 也被转换（cmd 进入交互模式只打印版本横幅），须写 `cmd //c "taskkill /F /IM …"` 才真正执行；加 `MSYS_NO_PATHCONV=1` 前缀则单斜杠可直接用。**两版并存**：原文现象（`//F` 静默失败）若在特定 MSYS 版本/配置上成立，请补版本号；本机适用范围是 Git Bash 5.2.37——正确写法为 `//X`、或 `cmd //c "…"` 包装、或 `MSYS_NO_PATHCONV=1` 前缀。

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

- **验证于**：Windows 11 家庭中文版 10.0.26200.9457 · Git Bash 5.2.37 · Python 3.12.10 · Node v24.18.0 · 2026-09-21
- **复测出入（2026-09-21：假空复现了，但扳机不是"中文"，是长度；方向也和原文相反）**，三面都在 temp 造、跑完留在 temp：
  ① **短**路径（总长 53）里同时放中文、空格、以及**目录名带 `[ ]`** 的目录：通配工具、`python os.listdir`、`bash ls` **三通道全部正常列出**。
  ⇒ "中文/空格/方括号会让通配层假空"这一支未复现。
  ② 同样的名字嵌到 **总长 263（目录）/270（文件）的纯 ASCII** 路径：`os.path.exists()` = **False**、`os.listdir` = `FileNotFoundError(3)`，
  而 `node` 的 `readdirSync` 与 `bash ls` **照常列出那个文件** ⇒ 假空确实存在，但 ASCII 与中文同形，所以成因是 §11 那条 MAX_PATH 阈值，不是编码。
  ③ 同一条 >260 的路径交给通配工具，返回的不是 `No files found` 而是一句 `spawn <安装目录>\…\rg.exe ENOENT`——
  那个 exe 用 `ls` 明明在（5 444 592 字节）。**报错文案指着"二进制不存在"，真因是子进程的工作目录在 Win32 查找层不存在**，与 ② 同源。
- **对策加一句（本轮实测得出）**：换通道要换**不同家族**——MSYS coreutils、libuv(Node)、Win32-native(Python/PowerShell) 各算一族；
  同族两条一起瞎会伪装成"两边都同意这里没东西"。另外 8.3 短名在这一档**救不回来**：
  实测中文段的短名仍是非 ASCII、总长仍 >260，Python 依旧 `FileNotFoundError(3)`；越界就读不到时，唯一稳的做法是缩短结构本身（§11 对策 ③）。

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

- **验证于**：Windows 11 家庭中文版 10.0.26200.9457 · Git Bash 5.2.37 · coreutils(md5sum/wc) · 2026-09-21
  （活测：同一份 6 字节文件 `alpha\n`。`md5sum < f` = `9f9f90db…`；
  `V=$(cat f)` 之后 `printf '%s' "$V" | md5sum` = `2c1743a3…` ⇒ **DIFF**；
  改 `printf '%s\n' "$V"` = `9f9f90db…` ⇒ **SAME**；空输入基准 = `d41d8cd98f00b204e9800998ecf8427e`（与原文一致，一眼可认）。
  字节侧对上：`wc -c <<<"$V"` 回 6（herestring 自己补了一个换行，别拿它当证据），`printf '%s' "$V" | wc -c` 回 **5**，文件本身 6 ⇒ 差的正是结尾那一个换行。
  `diff f g` 空 = 唯一该信的读法，本轮同时验证了它对同内容文件的判定。）

## 11. 路径总长到 260 字符：一些工具照常成功，另一些连"文件存在"都看不见

- **现象**（本机实测，绝对路径长度逐字符可控）：把目录嵌深到**总长 260 字符以上**后，同一批工具分成两组——
  - **照常成功**：Node `fs.writeFileSync` / `fs.readFileSync`（300 字符路径退出码 **0**，读回 5 字节）、Git Bash 的 `cp` / `>` 重定向 / `wc -c`（300 字符退出码 **0**、报出字节数）。
  - **直接失败**：Python `open()` / `os.stat()`、PowerShell `Get-Content` 在 **260 起**一律 `FileNotFoundError(2, 'No such file or directory')` / `ItemNotFoundException`；`os.path.exists()` 返回 `False`；`cmd copy` 报 `系统找不到指定的路径`；`git add` 退出码 **128**（`error: open("…")`）。
  - **最容易读反的一档**：`cmd copy` 在**目标**路径越界时打印 `已复制         0 个文件。`、退出码 **1**——句式像成功、数字是 0；`pwsh New-Item -Directory` 到总长 250 就报 `完全限定文件名必须少于 260 个字符，并且目录名必须少于 248 个字符`。
  - 后果是本族最典型的坏结论：Node/bash 明明把文件写出来了，Python 一句 `False` 就让你判"没生成 / 目录是空的"，然后开始重建（与 `silent-failure-triage §2`、本文件 §9 同族）。
- **根因**：`LongPathsEnabled` 未开启时（本机实测值 `0`），不带 `\\?\` 前缀的 Win32 路径要过 MAX_PATH 检查，**下列三对阈值都是「不加 `\\?\` 前缀的 Win32 调用」的实测值**（本节用 Python `open()` / `os.mkdir()` 测得）：文件 **259 成功 / 260 失败**、目录 **247 / 248**、进程工作目录 **258 / 259**（`CreateProcess` 抛 `NotADirectoryError`）。官方的 260 / 248 是含结尾 NUL 的口径，所以能落地的最长值比它小 1。**失败文案还分两档**：248–259 报 `文件名或扩展名太长`，260 起报 `系统找不到指定的路径`（同族：`WinError 3`）——可以拿它反推自己在哪一档。⚠️ **阈值是工具相关的，不是平台常量**：Node 的 libuv 自动补前缀，同一台机器上 `fs.mkdirSync` 在 248 / 259 / 260 / **300** 全部成功；MSYS coreutils 同理。所以复核这两对数字**必须用 Python（或另一条同样不加前缀的通道）**，拿 Node / PowerShell 去测必然对不上——本节说的「Node 与 MSYS 是例外」就是这条。**相对路径不是绕法**：API 仍按 `cwd + 相对名` 拼成绝对路径再判，实测 cwd 长 242 时相对名 40 → 解析后 264 → 照样失败。
- **对策**：① 确实要越界时，命令里显式写 `\\?\<绝对路径>`——实测 Python、PowerShell 接受；`cmd` 报 `指定的路径无效。`、git 报 `fatal: Invalid path '//?/…'`（前缀会被 MSYS 改写成 `//?/`，所以 git 侧只能靠缩短路径）；② **`\\?\` 不能当进程工作目录**：`CreateProcess` 收到它会静默把 cwd 降级为 `<盘>:\Windows`、命令退出码 **0**，此后所有相对路径操作都落在系统目录里；③ 把长路径当**结构信号**——它通常说明中间产物该挪到浅目录；④ 临时救急可换 8.3 短名（`cmd /c "for %I in (…) do @echo %~sI"`，见本文件 §8），实测把 260 压到 133、300 压到 151、400 压到 196，且短名可被 Python 正常 `open()`。
- **判定**：同一文件过三条通道比对，出现分歧即命中本节：

  ```bash
  P="<盘>:\<深>\<深>\<文件>"                            # 绝对路径
  printf 'len=%s\n' "$(printf '%s' "$P" | wc -c)"       # ≥260 即落在本节范围
  python -c "import os,sys;print('py  ',os.path.exists(sys.argv[1]))" "$P"
  node   -e "console.log('node',require('fs').existsSync(process.argv[1]))" "$P"
  ```

  `node` 为 `true` 而 `py` 为 `False` ⇒ 文件真实存在、只是 Python 看不见 ⇒ 命中本条，**不要**据此重跑生成。需要贴边判定时按这三对阈值卡（**均为 Python 不加前缀调用的口径**）：259 成功 / 260 失败（文件）、247 / 248（目录）、258 / 259（工作目录）。换 Node / PowerShell 复核会得到不同的数，别据此判本节错——先看根因那段的工具标注。
- **验证于**：Windows 11 家庭中文版 10.0.26200.9457 · Git Bash 5.2.37 · Git 2.53.0.windows.2 · Node v24.18.0 · Python 3.12.10 · PowerShell 5.1.26100.9444 · 2026-09-17
- **复测确认（2026-09-19，另一 agent 独立复跑 + 二次更正）**：文件侧 **259 成功 / 260 抛 `FileNotFoundError` errno=2，与本节逐字一致**。目录侧它最初在 247 / 248 看到 `list OK`，先后提过两个解释（「base 路径长度造成的偏移」、以及本节初稿猜的「Node 走 libuv 补前缀」）——**两个都不对，真因由它自己重跑后定位**：那份脚本**用 `\\?\` 前缀去建目录、再用不带前缀的短路径去 `listdir` 探边界**，于是**建侧闸门被前缀绕开**、探到的是**列侧闸门**，才有了「247/248 OK、258/259/260 才报错」的偏移观感。换成与本节相同的通道（**无前缀 `os.mkdir`**）后它在 base 60 与 85 两组下断点逐字节一致：**246/247 OK、248 FAIL**；我自己另用 base 53 与 75 复核同得 247 OK / 248 FAIL ⇒ **阈值只由完整路径长度决定、与 base 无关**。失败文案两档也完全对上（248–259 `文件名或扩展名太长`（WinError 206）vs 260 起 `系统找不到指定的路径`（WinError 3））。
- **注意：建侧与访问/列侧不是一个闸门**（上条那个偏移观感的来源，值得单独记）：用前缀建出的目录，**不带前缀去 `listdir` / `os.stat` 在 248–255 仍成功**，而**不带前缀去 `os.mkdir` 在 248 就失败**。所以本节「247 / 248」指的是**创建**的上限；已存在的路径“能不能访问”要宽到 259/260 那一档（文件口径），两件事别混。
- 教训（两次踩同一个）：本条的数字必须连同**测量通道**（用不用前缀、哪个 API）一起引用；且探边界时**建与探必须用同一通道**，否则你量到的是另一个闸门。

## 12. junction 的"是链接"每个工具答得不一样；吃掉目标的是尾反斜杠和 `del /f /s /q`

- **现象**（本机实测；样本均为 junction：`%USERPROFILE%\.trae-cn\skills` → `<工作区>\trae-data\skills`、`%USERPROFILE%\.agents\skills` → `<工作区>\agentskills`）：
  - PowerShell 5.1 `(Get-Item -Force <路径>).LinkType` → 这两个都是 `Junction`，`.Target` 是目标绝对路径；普通目录（`<工作区>\agentskills`）返回**空**。
  - Git Bash：`[ -L <链接> ]` 对 junction 报 **yes**（反斜杠原生写法与 `/d/…` POSIX 写法都 yes）。但**路径尾部多一个 `/` 或 `\` 就立刻变 no**——尾斜杠会先解析进目录再判断，答的是"这个目录不是链接"。同一个链接、同一次运行，两种写法答案相反：这里出错的是**路径形态**，不是 MSYS 不认 junction。
  - Python 3.12：`os.path.islink()` False；而 `pathlib.Path.is_junction()` True。
  - Node 24：`lstat().isSymbolicLink()` **两种都出现过**——对上面两个 junction 是 true；对系统自带的 `%USERPROFILE%\AppData\Local\Application Data`（junction → `...\AppData\Local`）**是 false**。别把 `isSymbolicLink()` 当裁判。
- **根因**：junction 是 NTFS 重解析点（`fsutil reparsepoint query` 报 `Tag value: 0xa0000003`），与符号链接是**另一个 tag**，Windows 对使用者透明；各工具链按自己的模型实现，所以答案分叉：Python `os.path.islink()` 只认符号链接那个 tag，对 junction 一律 False；MSYS 会把 mount-point tag 当链接，所以裸路径答 yes——但任何"先解析再判断"的写法（尾斜杠、`/…/.`、`Path.resolve()` 之后再问）拿到的都是解析后的普通目录，于是回答 no。**no 不一定是"认不出链接"，也可能是"根本还没看到链接"；两者后果相同：被当成普通目录去遍历和删除。**
- **对策**：
  - 识别一律读原始属性，别信包装函数：`$i=Get-Item -Force -LiteralPath <路径>; $i.LinkType`、`$i.Attributes -match 'ReparsePoint'`、`fsutil reparsepoint query <路径>`。
  - 要"看最终落到哪"就用会解析的：Node `fs.realpathSync()`、Python `Path.resolve()`；再拿 `os.path.islink()` / `is_junction()` 判断中间有没有链接层。
  - 删链接前先确认它**本身是**重解析点；删除只用 `rmdir "<链接>"`（不带 `/s`）或 `Remove-Item -LiteralPath "<链接>" -Recurse -Force`——后者实测五种写法（带/不带尾反斜杠、`-LiteralPath`、`-Path`、目标里有只读文件）都是**链接没了、目标里的文件全在**，可以放心用。
  - **尾反斜杠是这里的真实开关**：同一条 `rmdir /s /q`，写 `"<链接>"` 只删链接，写成 `"<链接>\"` 就**穿透删掉目标里的内容**（两轮独立运行、`rmdir /s /q` 与 `rd /s /q` 两种写法都复现，链接与目标目录还在原地、里面已空）。`rmdir "<链接>\"` 不带 `/s` 又安全。也就是说：**危险不是 `/s /q` 这个参数组合，而是"路径以分隔符结尾 ⇒ 命令进到目标里面去删"**。
  - **无条件禁止**的是 `del /f /s /q "<链接>"`：不带尾反斜杠也照样穿透，退出码 0、打印"删除文件 - …"、链接本身反而还在（`linkGone=false` 而目标里的文件已消失，三次独立复现）。这就是"删链接把别人数据删了"的真身。
  - 嵌套情形要当心：`%USERPROFILE%\.codex` 是 junction → `<工作区>\codex`；但 `.codex\skills` 不是重解析点（`fsutil` 报 `文件或目录不是重解析点`、`LinkType` 空），它是**穿过**上层 junction 落在目标里的真目录——此时 PowerShell 的 `[string] $i.Target` 还能给出一个看起来合法、实际不存在的前缀路径（它给的是 `C:\<工作区名>\codex\skills`，而该路径 `Test-Path` 为 false；Node `realpathSync` 给的是 `<工作区>\codex\skills`）。**LinkType 为空时就不要读 Target。**
  - git：把 junction 放进工作树，`core.symlinks=false` 管不了它，Git 会把目标整棵树当普通内容——实测 `git add link` 后 `git status` 是 `A  link/file0.txt`（目标里 4 个文件全部入库）；跨副本仓库里一个 junction 就能把几百 MB 拉进提交。
  - 通过 junction 进仓库目录（`cd link && git …`、`git -C "<junction>"`、Node `spawnSync(..., {cwd})`）都是**正常解析到真身**的，`rev-parse --show-toplevel` 返回真实路径，不必绕开。
- **判定**：① 识别：`fsutil reparsepoint query <路径>` 退出码 0 且输出含 `0xa0000003` ⇒ 是 junction（普通目录 ⇒ 退出码 1、`文件或目录不是重解析点`）；② `Get-Item -Force <路径>` 的 `LinkType` 等于 `Junction` ⇒ 是链接，`Target` 可读；③ 删除安全性，用一次抛弃型实测证明（只在一次性 scratch 目录里做，目标自己造）：建 `tgt\keep.txt` 与 `tgt\sub\deep.txt`，`mklink /J lnk tgt`，然后**同一命令两种写法各跑一遍**——
  ```bat
  rmdir /s /q "<scratch>\a\lnk"      :: 链接没了，a\tgt\keep.txt 与 sub\deep.txt 都还在
  rmdir /s /q "<scratch>\b\lnk\"     :: 链接没了，b\tgt 目录还在但内容已全被删空
  ```
  两种写法结果不同 ⇒ 命中本条（尾分隔符才是开关）；`del /f /s /q "<scratch>\c\lnk"` ⇒ 打印"删除文件 - …"、退出码 0、`c\lnk` 仍在、`c\tgt\keep.txt` 已消失。**"退出码 0 + 目标内容消失"这一对就是本节的判定标准。**
  - **同一行命令的调用点也决定结果（2026-09-18 两版并存，由仓库维护者裁定）**：上面"非空 → 强制确认（子项）"是**交互式控制台**下的形态；在 **`powershell -NoProfile -Command` 非交互调用**下实测到的不是确认提示，而是直接失败——目标为空时 `Remove-Item "<链接>"` 与 `-LiteralPath` 均 exit=0、链接被删、目标目录仍在；目标非空（3 个文件）时 positional / `-LiteralPath` / `-Confirm:$false` / `-Force` **全部 exit=1、链接与文件原样保留**，英文机文案为 `Remove-Item : Object reference not set to an instance of an object.`；加 `-NonInteractive` 则文案变为"在非交互模式下提示不可用"。两版适用范围不同、不互相覆盖；要安静且确定地只删链接，用 `-Recurse`（是否加 `-Force` 均可）。
  - 附两条同族坑：`dir /al` 在"父目录没有重解析点"时退出码是 **1**、stderr 为 `File Not Found`——与"路径不存在"完全同形，别用它判断链接是否存在；PowerShell 5.1 的 `Remove-Item "<junction>"`（不带 `-Recurse`）分两态：目标**为空**时直接删成功、退出码 0；目标**非空**时是一条**强制确认**（"项具有子项…"），`-Confirm:$false` 和 `-Force` 都压不住，非交互调用（`-NonInteractive`）下变成 `InvalidOperation`「在非交互模式下…提示不可用」而**链接与目标都原样保留**——想安静删掉就得给 `-Recurse`。（2026-09-18 两版并存：本行为交互式控制台口径；上面那条为 `powershell -NoProfile -Command` 非交互口径，两者互不覆盖，由仓库维护者裁定。原稿曾记为"报 `Cannot find path …`、退出码 1"，复跑与悬空 junction 两种情形都未复现，故不再保留该写法；PowerShell 7 未测。）
- **验证于**：Windows 11 家庭中文版 10.0.26200 · PowerShell 5.1.26100.9444 · Git Bash 5.2.37（MSYS 3.6.6-1cdd4371 / git 2.53.0.windows.2）· cmd 10.0 · Python 3.12.10 · Node v24.18.0 · 2026-09-17 首发，2026-09-18 独立复跑并更正 `[ -L ]`、`Remove-Item`、`rmdir /s /q` 三条

## 13. 测量工具会静默消解被测对象的语义

- **现象**（本机自伤两次，同一节里连撞）：给"junction 是不是链接"做判定时，我的探针先输出"Git Bash `[ -L ]` 恒为 no"、后被独立复核否证——真值是**裸路径 yes、带尾斜杠 no**；同一轮里另一条"`rmdir /s /q` 会穿透明"也被否证为**只有路径以分隔符结尾才穿透**。两次结论都错在**测量管道**，不在被测对象：① 路径转换函数用了 `fs.realpathSync()`，它把 junction 解析成目标，于是"测链接"实际测的是**解析后的普通目录**；② 命令字符串拼装时引号/尾分隔符被吞掉或预展开（cmd 里 `%{…}` 会被当变量、`&` 会把退出码读早），于是发的不是原来那条命令。
  另有两个同类现场：③ 想把"一行标注 + 一整节新增"拆成两个提交，用 `git apply --cached` 配合手挑 hunk，粒度不够精确，把两处一起暂存进了第一个提交（暂存卫生与显式路径纪律见 `git-ref-plumbing-on-windows §9`；`apply --cached` 这个变体该节尚未收录）；④ 探针脚本写在"待清空目录"里，脚本开头清空该目录 → **把自己删了**，报告只含前半段而后半段静默缺失。
- **根因**：**测量工具链本身是带语义的**。任何"规范化 / 解析 / 转换路径"的步骤（Node `fs.realpathSync`、Python `Path.resolve()`、`Get-Item` 之外的隐式解析、shell 的引号与百分号展开）都会把"链接"换成"目标"、把"含尾分隔符的路径"换成"目录内部"。结果不是"测不到"，而是**测到了一个合法的、但不同的对象**——输出看着完全正常，所以比报错更危险。这与同族三类失效可对照：`silent-failure-triage §9`（单一否定结果不要当结论）、`shell-quoting-and-path-forms §12`（链接被当普通目录处理）、`silent-failure-triage §1`（管道吞掉真实退出码）。
- **对策**：
  ① **先钉身份再谈行为**：判定"这是不是链接"必须用**不解引用**的读取——PowerShell `Get-Item -Force -LiteralPath` 的 `LinkType`/`Attributes`、Node `lstatSync()`、Python `os.lstat()` 与 `Path.is_junction()`、`fsutil reparsepoint query`。**禁止**用 `Test-Path`、`Get-Content`、`Path.resolve()`、`realpathSync()`、`[ -d ]` 先"确认存在"再下链接结论——这些都会跨过链接。
  ② **转换路径的函数必须"不解析"**：Windows↔POSIX 路径转换只做字符替换与盘符小写（`D:\a\b` → `/d/a/b`），**不要顺手 realpath**；需要"最终落到哪"就把解析结果单独当成**第二个结论**，并明确标注"这是目标，不是链接"。
  ③ **命令发出前把实际参数回显出来**：在探针里先打印将要执行的完整命令行与其长度（或写盘再读回），确认尾分隔符、引号、百分号都没被吞。凡命令里出现 `%`、`$`、引号、尾 `\`，这一步不是可选项。
  ④ **测量动作本身也进 scratch 目录**：探针脚本不要写在"待清理 / 待删除"的目录里（本轮真事故：复测脚本写在待清空的 repro 目录里，脚本开头清空该目录 → **把自己删了**，只跑了前半段，后半段静默缺失）。
  ⑤ **两法交叉**：同一结论至少用两条互不依赖的通道各跑一次（原始属性 vs 解析结果 vs 命令行回显）；二者不一致时，先怀疑测量管道，再怀疑被测对象。
- **判定**：① 回显检查——同一条路径在探针里打印 `[ -L "$p" ]` 的原始形态必须是**你要测的那个字符串**（裸路径不带尾 `/`、不经过 realpath）；若你打印出的已是解析后的路径，本条即命中。② 形态对照——同一次运行里 `p=<裸路径>` 与 `p=<裸路径>/` 必须给出**不同的**结果（junction 样本上实测即为 yes/no 两值）；若两者答案一样，先评估是不是测量管道把它们都解析成了同一个人。③ 产物自检——探针结束后确认报告文件的时间戳/行数与预期段数一致（本轮事故：报告只含前半段，后段因脚本自删而缺失）；报告缺段即测量管道不完整，结论不能采信。
  ④ 显示层复核——"看到乱码"不等于"内容坏了"：控制台按自身代码页渲染 UTF-8 时会把正确的中文显示成乱码（`windows-text-encoding §2`、`runtime-resolution-and-abi` 编码交叉），**先按字节复核再动手**——`python -c "print(open(f,'rb').read(3).hex())"` 或 Node `fs.readFileSync(f)` 打印码点计数；仅凭终端观感就去"修复"，会把好文件改坏（本轮实测：差点据此修一个内容正确的节，字节复核后 mojibake 标记数为 0）。
- **验证于**：Windows 11 家庭中文版 10.0.26200 · Node v24.18.0（探针宿主）/ Git Bash 5.2.37 / Windows PowerShell 5.1.26100.9444 · git 2.53.0.windows.2 · 2026-09-18

## 14. PowerShell 5.1 没有 `if` 表达式：报错指向 `if`，让人以为整条命令坏了

- **现象**（本机实测）：把 `if` 当表达式用在格式化输出里——
  ```powershell
  "{0} 可达={1}" -f $n, (if ($x) { 'yes' } else { 'no' })
  # → if : The term 'if' is not recognized as the name of a cmdlet, function, script file, or operable program.
  ```
  报错把 `if` 说成"不认识这个命令"，读起来像**整条命令**坏了，实际只是那个充当 `-f` 操作数的括号组不合法。
- **根因**：Windows PowerShell 5.1（`PSEdition=Desktop`）**没有** `if` 表达式、没有三元 `? :`。
  它只有**语句** `if`；写成 `(if (...) {...} else {...})` 时解析器把 `if` 当**命令名**去找。
  三元 `? :` 是 PowerShell 7 才有的；而 `$(if (...) {...})` 这种**子表达式**在 5.1 与 7 里都合法。
- **解法**：用子表达式 `$(...)` 包住语句块——
  ```powershell
  "{0} 可达={1}" -f $n, $(if ($x) { 'yes' } else { 'no' })
  ```
  或先算进变量再格式化（最稳，且中间值可回显）。
- **先分辨你在哪个 PowerShell**：`$PSVersionTable.PSVersion` + `PSEdition`。
  实测本机工具链里那个叫 `pwsh` 的**实际是 5.1 Desktop** —— 名字不可信，`PSEdition` 可信
  （与 `runtime-resolution-and-abi` 同主题：先钉身份，再谈行为）。
- **真正的危险不是报错，是"部分执行"**：长脚本里这类**显示层**语法错误可能在前面几句**已经跑完**之后才抛。
  于是现场是"半执行状态"，却极易读成"整段没跑"。
  对策：多步命令**每步各回显读数**（别拿下一步的绿推断上一步跑了）；写脚本时把"算值"与"打印"分开，
  不要往格式化参数里塞逻辑。
- **判定**：报 `The term 'X' is not recognized`，而 `X` 是语言关键字（`if`/`else`/`for`）而非你的程序名时，
  先怀疑**宿主 PowerShell 版本的语言特性差异**，不要去 PATH 里找可执行文件。
- **验证于**：Windows 11 家庭中文版 10.0.26200 · Windows PowerShell 5.1.26100.9444（PSEdition=Desktop）· 2026-09-19
  （实测：`(if (...) {...})` 用作 `-f` 操作数报 `The term 'if' is not recognized`；改 `$(if (...) {...})` 后通过。）

## 15. 长正文别当命令行参数传：写文件 + `-F` / `--file`

- **症状**（本包踩了**两次**）：`git commit -m $msg` 而 message 里含 ASCII 双引号
  （例如 `造一个"把 --panel-bg-l1 定义为深色"的页面`）→
  ```
  git : error: unknown option `panel-bg-l1'
  usage: git commit ...
  ```
  message 里的一段被当成**选项**了。
- **根因**：PowerShell 把参数交给原生命令时，内嵌双引号被当作**参数边界**，参数被拆成多段；
  git 看到以 `-` 开头的那段就当选项。凡正文里可能出现引号、反引号、`$`、分号、中文标点，
  **转义拼装就不可能可靠**。
- **对策**：**长正文一律走文件**，不要塞进参数。
  - `git commit -F <file>`（本包已固化用法）
  - 其他 CLI 找 `--file` / `--input` / `--file=-`，或走 stdin（`Get-Content x | prog`）
  - 临时 message 文件放**仓库外** —— 放仓库内会被 `git add -A` 一起提交（本包踩过一次）
- **⚠️ 教训的方向要选对**：第一次我用「」替换掉双引号绕过去了，那**只治了症状**，
  换个文本又中招。**「别用双引号」是错的教训；「别把长正文当参数传」才是对的。**
- **判定**：报错里出现 `unknown option 'X'` 且 `X` 是你正文里的某个片段 → 本条命中。
- **验证于**：Windows 11 家庭中文版 10.0.26200 · Windows PowerShell 5.1.26100.9444 · git 2.53.0.windows.2 · 2026-09-19
  （实测：含双引号的 message 报 `unknown option`；改 `git commit -F 文件` 一次成功。报错里的变量名已中性化。）

## 16. PowerShell 方法调用的参数位不能写运算符表达式：报错说"重载找不到"，真因是参数被拆成两个

- **现象**（本机实测）：清理脚本里写
  ```powershell
  $stamp = [regex]::Escape($today -replace '-','')
  # → 找不到“Escape”的重载，参数计数为:“2”。
  ```
  报错说的是**重载不存在**，读起来像 `Escape` 这个方法不能这么调；实际是 `-replace` 的逗号被当成了**方法参数分隔符**，`Escape` 收到两个参数。中文区域下这条文案还带**全角引号**（`“Escape”`、`“2”`），拿 `grep -F '"Escape"'` 去搜日志会 0 命中（全角符号破坏可检索性，见 `shell-quoting-and-path-forms §3`）。
- **根因**：方法调用 `接收者::方法(a, b)` 的参数表按逗号切分，**只做表达式求值**；`-replace`、`-split`、`-join`、`-in`、`-f` 这类**带连字符的操作符是命令形态**，出现在参数位时它自己那套 `操作数1, 操作数2` 的逗号会被上层参数表再切一次。同一个表达式写在赋值右侧（`$x = $today -replace '-',''`）完全合法——所以"这句我单跑过没问题"不能否证本条。
- **对策**：
  ```powershell
  $t = $today -replace '-',''      # ① 先算进变量（可读性最好）
  [regex]::Escape($t)
  [regex]::Escape(($today -replace '-',''))   # ② 括号显式成组，实测同样通过
  ```
  凡是"方法参数位"要放运算符表达式，一律走这两形之一；**参数位里出现 `-字` 开头的内容时先怀疑本条**。
- **⚠️ 危险放大在错误偏好**：这类脚本常配 `$ErrorActionPreference='SilentlyContinue'`，于是报错被吞、`$stamp` 变 null、后续按日期挑文件的正则退化成匹配一切（或一切都不匹配），**清理脚本照常打印"完成"**。凡批量删除/搬移前置条件来自一次计算值的，必须**当场回显该值**再进入删除分支。
- **判定**：报错文案含 `的重载` 或 `overload` 且带 `参数计数为:“N”`，而 `N` 比代码里写的参数个数大 ⇒ 本条命中；逐个检查参数位里是否有带逗号的 `-操作符`。反证一条：把该表达式挪到赋值右侧后错误消失 ⇒ 确诊。
- **验证于**：Windows 11 家庭中文版 10.0.26200 · Windows PowerShell 5.1.26100.9444（LanguageMode=FullLanguage）· 2026-09-21
  （实测三写法：原写法报 `参数计数为:“2”`；先算变量、以及外层再加括号，两种均通过。）

## 17. 属性不存在不报错，只静默给 $null：分类器全判否、整批被跳过，脚本仍报成功

- **现象**（真实事故 + 本机复现）：抓取脚本按扩展名筛文本资产——
  ```powershell
  $ext = [System.IO.Path]::GetExtension($b.path).ToLower()
  if ($TextExt -notcontains $ext) { $binSkip++; continue }
  ```
  实跑结果 **整批候选全部走 skip 分支**，汇总打印"成功 0、失败 0"，退出码正常。
  本机最小复现（两条独立样本，`$Error.Count` 增量为 **0**）：
  ```powershell
  foreach ($b in @('x/USAGE.md','a/b/shot.png')) {     # $b 是字符串，没有 .path 这个属性
    $ext = [System.IO.Path]::GetExtension($b.path).ToLower()
    Write-Output ("ext=[" + $ext + "] skip")           # → ext=[] 两条都被跳过，无任何报错
  }
  ```
  同族第二形：`ConvertFrom-Json` 出来的对象字段叫 `file_path` 而代码读 `.path` —— 该条静默跳过，另一条正常（**一批里部分对部分错，比全错更难发现**）。
- **复测更正（与本条原始归因不一致，两版都保留）**：原始 lesson 记为"`[类型]::方法($obj.属性).链式成员()` 这种**调用后链式取成员**被 PowerShell 解析成 null"。本轮**未复现该归因**：同一写法在 `[pscustomobject]` 与 `ConvertFrom-Json` 两种对象上都正常返回 `.md`（PS 5.1.26100.9444 / FullLanguage）。真复现的路径是**属性本身不存在**。原脚本已不可定位，故不坚持原归因；下面按实测机制写。
- **根因**：非严格模式下，读一个不存在的属性**返回 `$null` 且不产生任何错误记录**（这不是"报错被 `-ErrorAction Continue` 压住了"——是根本没有错误记录，所以任何"看有没有报错"的自检都放行）。`$null` 喂进 .NET 静态方法 → 拿到空串 → 与白名单**永远不相等** ⇒ 每个元素都判否 ⇒ `continue` 分支把整批静默吞掉。两个附带读数：① PowerShell 属性访问**大小写不敏感**（JSON 里是 `Path` 也能被 `.path` 读到），所以"大小写写错"不是原因，**字段名根本对不上**才是；② 纯 PowerShell 命令不设置 `$LASTEXITCODE`，脚本里读到的 `ExitCode` 是空值——拿它当"成功"依据也是假信号。
- **对策**：
  ① **脚本开头两行**（实测把静默变成当场失败）：
  ```powershell
  Set-StrictMode -Version Latest
  $ErrorActionPreference = 'Stop'
  # 同一条 ('a.md').path 在 StrictMode 3 下报：在此对象上找不到属性“path”。请确认该属性存在。
  ```
  ② **跳过计数进汇总，且 100% 跳过即失败**：`if ($total -gt 0 -and $skip -eq $total) { 'SELFTEST FAIL: 判据恒假'; exit 1 }`。"没活干"和"判据恒假"必须能区分。
  ③ **分类器启动自检**：拿白名单里的值反向喂给自己的提取逻辑（`.md` 提取后仍应是 `.md`），对不上就退出——判据错要**当场响**，不许跑到最后。
  ④ **回显提取值本身**：过滤分支打印 `ext=[...]`，空值一眼现形；只打印"跳过 N 个"看不出是值错还是数据本来就没有。
  ⑤ **单测通过 ≠ 脚本内通过**：独立验证时喂的是**字面量**，脚本里喂的是**属性/元素**，两者形状不同；进脚本后要端到端再跑一次并核对计数。
- **判定**：批处理汇总里出现 `成功 0、失败 0` 或 `跳过 == 总数` ⇒ 先当"判据恒假"处理，不要当"没有数据"。确诊三步：① 打印 `$b.GetType().Name`（是 `String` 还是 `PSCustomObject`？）；② 打印提取值 `[…]"`（空 ⇒ 命中本条）；③ 加 `Set-StrictMode -Version Latest` 重跑，若立刻报"找不到属性 X"⇒ 属性名与被喂对象的字段不一致，改名或按实际 schema 取键。
- **验证于**：Windows 11 家庭中文版 10.0.26200 · Windows PowerShell 5.1.26100.9444（LanguageMode=FullLanguage，ConsoleHost）· 2026-09-21
  （实测：字符串数组上取 `.path` → `$Error` 增量 0、两条全跳过；`file_path` 键 → 同形静默跳过；`Path` 键大小写不同 → 正常读到，证明大小写不是变量；`Set-StrictMode -Version 3` 下同一条报"找不到属性"。）

## 18. 正则方言与引擎不匹配时"扫干净了"是假的：ERE 静默 0 命中、`\U` 吃引号层、`-P` 不吃 `-f`

- **现象**（同一份含目标串的数据，三种写法各自给出 0 命中）：
  ① `grep -RIl -E '(?!9222)Users' <面>` → **rc=1、stderr 空、0 行**（POSIX ERE 没有 lookahead）。它与"内容真干净"**完全同形**：同一面喂 `grep -RIl -E 'ZZZNOMATCHZZZ'` 得到**逐字段一样**的 rc=1 / stderr 空 / 0 行；把 lookahead 去掉用 `-E 'Users'` 立刻命中 1 个文件。
  ② `grep -RIl -P` 的模式里反斜杠层数错一位就报 `grep: PCRE does not support \L, \l, \N{name}, \U, or \u`，然后**不产出任何行**（rc=2）。触发点**取决于引号层**，不是"写几个反斜杠看着像"：单引号里 `'C:\Users'`（1 个）就报、`'C:\\Users'` 正常命中；双引号里 `"C:\Users"` 与 `"C:\\Users"` **都报**，要写到 4 个才把 1 个送进引擎。
  ③ `grep -RIl -P -f patterns.txt` → `grep: the -P option only supports a single pattern`、rc=2、0 行；而**同一个模式文件**喂 `-E -f` 命中 2 个文件、喂 `-F -f` 命中 1 个。⇒ "为了 lookahead 把引擎换成 PCRE"这一步，会把整组批量规则一起降级成 0 命中。
- **根因**：**"0 命中"至少四种成因**——内容真干净 / 正则本身写错 / 方言与引擎不匹配 / **数据里根本没有那个形状**。其中只有 ②③ 会在 stderr 与 rc=2 留痕，① 连痕迹都没有；而脚本化扫描最常见的三写法（`2>/dev/null`、`subprocess` 默认不收 stderr、只看 stdout 空不空）恰好把唯一的痕丢掉。
- **对策**：① 需要 lookahead 就显式 `-P`——实测 `grep -RIl -P '(?!9222)Users'` 同一面命中 1；② `-P` 不吃 `-f`，批量模式改成 while-read 循环、**每条单独 `-e`** 各跑一次；③ 反斜杠不赌层数，**改用字符类** `[/\\]`、`[.]` 替掉字面量转义（实测 `'C:[/\\]Users'` 命中 1）；④ 固定字符串一律 `-F`，禁止任何元字符解释；⑤ **stderr 与 rc 一起进日志**，扫描器的"成功"要求净面 0 命中 **且** 探针命中 **且** rc/stderr 都在预期内。
- **本轮我自己踩到的两个"看着像方言错、其实是别的"**（比通则更难防，记下来免得重犯）：
  - 第一版反斜杠夹具的数据里**没有空格**，于是 `-E '\s'`、`-P '[[:space:]]'` 全给出 rc=1/0 行，我差点写成"GNU grep 不认 POSIX 字符类"。换一份**含空格**的数据重打，`-E`/`-P` 两种引擎下 `[[:space:]]`、`\s`、`\balpha` **六个组合全部命中**——是数据里没有，不是引擎不认。
  - 我拿 `(?!C:)Users` 当"必然 0 命中"的反向对照，结果它命中 1：lookahead 是**向前**看的，在 `Users` 那个位置它检查的是**后面**是不是 `C:`，与前面无关。断言方向记反，对照就白做。
- **同族（不同工具、同一个"0 命中不是证据"）**：Python `glob.glob('skills/*/SKILL.md')` 在 Windows 返回**反斜杠**路径（实测 `['skills\\dummy-skill\\SKILL.md']`），`p.split('/')[1]` 直接 `IndexError`；要父级目录名用 `Path(p).parts[-2]`（实测得 `dummy-skill`）。
- **判定**：一次扫描只在**同时**满足三条时才算"干净"——净面 0 命中、**同一被扫面内**注入的对照命中 > 0（**逐条模式各证一次**，不能一条证全局）、rc 与 stderr 都在预期内。"逐条各证一次"不可省：`-P -f` 那一类失效正是整组一起变 0 的那种。
- **验证于**：Windows 11 家庭中文版 10.0.26200.9457（zh-CN）· Git for Windows 自带的 GNU grep 3.0 · Git Bash 5.2.37(1)-release(x86_64-pc-msys) · Python 3.12.10 · 2026-09-21
  （①②③ 三条、两条自踩纠正与 glob 反斜杠都是本轮同一 temp 目录内跑完的读数，夹具为 3 行，其中一行的形状是"盘符 + 单反斜杠 + Users + 单反斜杠 + 一个占位账号名 + \x.txt"（占位名，非真实账号）；引号层矩阵为单引号 1/2、双引号 1/2/4 共五格实测。**未测到的部分**：结论只在这台机器的 GNU grep 3.0 上取，未覆盖 busybox/ripgrep/Windows 自带 `findstr` 的方言边界。）
