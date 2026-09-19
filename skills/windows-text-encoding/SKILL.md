---
name: windows-text-encoding
description: Windows 文本编码、BOM 与行尾判定手册。写/改 PowerShell 脚本、批处理 .bat、含中文的数据文件、脚本“运行成功但输出乱码”、读别人给的文件出现替换字符、本地文件哈希与仓库 blob 对不上之前读。触发词：乱码、编码、BOM、efbbbf、fffe、UTF-16、GBK、cp936、chcp、Get-Content、Out-File、Set-Content、PYTHONUTF8、preferredencoding、CRLF、autocrlf、invalid start byte、中文变问号、脚本改完不生效。
agent_created: true
---

# Windows 编码与 BOM

一句话原则：**编码正确性由消费端的解析器决定，不由文件内容决定**。所以每条判定都要落到字节层，肉眼和 diff 都看不见这类错误。

## 1. `.ps1` 必须有 BOM，`.bat` 必须没有——同一个套路里要求相反

- **现象**：含中文的 `.ps1` 在 Windows PowerShell 5.1 下报 `The string is missing the terminator`，或脚本"改了不生效"；反过来给配套的 `.bat` 也补 BOM 之后，cmd.exe 把 `EF BB BF` 当命令文本，首行 `@echo off` 失效（报 `'﻿@echo' 不是内部或外部命令`）。
- **根因**：PS 5.1 把无 BOM 的 UTF-8 按系统 ANSI(GBK) 解码；cmd.exe 的解析器不接受 BOM。
- **对策**：`.ps1` 存 UTF-8 with BOM、`.bat` 存无 BOM 且注释尽量纯 ASCII（要中文就 echo 英文）；`.bat` 固定用 `powershell -NoProfile -ExecutionPolicy Bypass -File "<绝对路径>.ps1"` 起脚本。
- **判定**：成对断言首三字节，别只看文件名。
  ```bash
  head -c 3 a.ps1 | xxd   # 期望 ef bb bf（就这三个字节；无 BOM 时这里可能是行首 ASCII，见下）
  head -c 3 a.bat | xxd   # 期望不是 efbbbf
  ```
  两个读数陷阱：① **无 BOM 时首三字节取决于首行写了什么**——实测 `# 中文注释` 打头的无 BOM UTF-8 `.ps1` 是 `23 20 e4`（`#`+空格），不是内容编码的特征串，分类要先跳过行首 ASCII（命令见 `runtime-resolution-and-abi §7` 判定第 2 岔）；② **补 BOM 只修好读入方向**。实测同一个 `Write-Output '中文'`，带 BOM 版进程内部码点正确（`4e2d,6587`）但 **stdout 原始字节是 GBK `d6 d0 ce c4`**，按 UTF-8 解码的下游反而在这版看到乱码；要稳定 UTF-8 输出得另设 `[Console]::OutputEncoding`。写读两个方向各断言一次，别给一个 BOM 就宣布两头都好（三层对照表见 `runtime-resolution-and-abi §7`）。
  PowerShell 侧：`[IO.File]::ReadAllBytes($p)[0..2]`。
- **验证于**：Windows 11 家庭中文版 10.0.26200.9457（zh-CN，ACP=OEMCP=936） · Windows PowerShell 5.1.26100.9444（本机无 pwsh 7） · Git Bash 5.2.37(1)-release(x86_64-pc-msys)（`xxd` 为其自带） · Python 3.12.10 · 2026-09-18（上面两个"读数陷阱"是本轮实测新增，含带 BOM / 无 BOM 两版 stdout 原始字节）

## 2. `Get-Content` 默认按 ANSI 读，读进来再写回去就永久损坏

- **现象**：读一个 UTF-8 中文脚本报乱码；或者"帮你修编码"的脚本跑完，文件里的中文全变成 U+FFFD 并**写回了原文件**——原文丢了。
- **根因**：PS 5.1 的 `Get-Content`/`Out-File` 默认走系统 ANSI，且默认写编码会覆盖原字节。
- **对策**：读 `Get-Content -Raw -Encoding UTF8`；写用显式 UTF-8（要 BOM 用 `New-Object System.Text.UTF8Encoding($true)` + `[IO.File]::WriteAllText`）。日志追加同样显式 `-Encoding UTF8`。
- **判定**：怀疑"内容坏了"之前先分清是显示层还是字节层——
  `python -c "b=open(p,'rb').read(); print(b.decode('utf-8')[:80])"` 能正常解出中文 = 只有控制台坏；解出的是乱码 = 文件本身已损坏，立刻停止再写。

## 3. 终端乱码不是文件坏：控制台代码页

- **现象**：脚本、文件、结果都对，只有终端里的中文是乱码；或 Python 打印中文抛 `UnicodeEncodeError`，而 `open(..., encoding='utf-8')` 写文件毫无问题。
- **根因**：控制台代码页非 UTF-8。中文 Windows 上常见 `sys.stdout.encoding=gbk`、`locale=cp936`，而文件系统编码是 utf-8——**坏在 print，不坏在 open**。
- **对策**：`chcp 65001` 后再看；或者干脆以脚本生成的报告文件为准（长输出本来就该落文件而不是靠终端）。Python 侧 `sys.stdout.reconfigure(encoding='utf-8', errors='replace')`。
- **判定**：`python -c "import sys,locale;print(sys.stdout.encoding, sys.getfilesystemencoding(), locale.getpreferredencoding())"` —— 三个值不一致即命中，且第一个才是终端。

## 4. 编码兜底代码被自己的异常处理吃掉（活体级陷阱）

- **现象**：脚本开头明明写了 `try: sys.stdout.reconfigure(errors='replace') except Exception: pass`，中文照样崩，而且**没有任何报错线索**——同目录结构相同的另一个脚本却是好的。
- **根因**：那个文件根本没有 `import sys`，`NameError` 被 `except Exception: pass` 静默吞掉，兜底变成 no-op；对照脚本导了 `sys` 所以正常。三层不可见叠加：默认 GBK 不报错 + 兜底被吞 + 差异只在逐文件比对才看得见。
- **对策**：**必须生效的初始化不要包在裸 `except: pass` 里**（要么收窄到 `except (AttributeError, ValueError)`，要么失败即打印并退出）；兜底代码和被兜底的资源要在同一处 review。
- **判定**：`grep -n "^import sys" <那个文件>`（没输出 = 兜底必然失效）；再 `python -c "import ast,sys;..."` 或直接跑一次看是否抛 `NameError`。

## 5. 仓库里的文本资产统一 UTF-8，读侧一律 `utf-8-sig` 打底

- **现象**：一个 YAML/JSON 被打包给下游（agent、CI、安装器）后读出来是 `????ֲ??????ϵͳ` 这种碎片；本地打开却"好像能看懂"。
- **根因**：文件由默认 ANSI 的工具链写出（真字节是 GBK），只有 Windows 本地编辑器会替你兜住；任何 UTF-8 消费者拿到的都是垃圾。
- **对策**：仓库内文本资产一律 UTF-8（`.ps1` 例外见 §1）；Python 读侧统一 `encoding='utf-8-sig'`（顺带吃掉 BOM，避免 `KeyError: '﻿name'` 这类首键污染）。
- **判定**：`python -c "b=open(p,'rb').read(); b.decode('utf-8')"` 抛 `UnicodeDecodeError: invalid start byte` → 非 UTF-8；再用 `.decode('gbk')` 解一次，能解出正常文字就是 GBK。

## 6. 扩展名不是格式证据

- **现象**：有人把 `.xlsx` 直接改名成 `.csv`。按文本读"成功"了，解出一堆乱码行，**不报错**，后续统计全部建立在垃圾上。
- **根因**：扩展名由人写，格式由字节定。
- **对策**：读二进制类文件前先嗅探再选引擎：
  ```python
  head = open(path, 'rb').read(8)
  if head[:4] in (b'PK\x03\x04', b'\xd0\xcf\x11\xe0'):   # zip(xlsx/docx) / OLE2(xls)
      ...交给表格引擎；别当文本读
  ```
  Office 文件本质是 ZIP：`zipfile` + `xml.etree` 直读 `word/document.xml` 往往比装解析库更快更稳（沙箱里装库本身还会失败）。
- **判定**：`zipfile.ZipFile(p).namelist()` 能列出 `word/document.xml` / `xl/worksheets/` = 它是 OOXML，不管扩展名叫什么。

## 7. `core.autocrlf` 在 `git add` 里静默改写行尾：工作树哈希 ≠ blob 哈希，而 git 说"干净"

- **现象**（Git Bash 全新 `git init` 的 scratch 仓库实测，未注入任何配置覆盖）：往工作树放一个内容确认为 **6 字节** `610d 0a62 0d0a`（即 `a\r\nb\r\n`）的文件：
  - `git add f.txt` → **退出码 0，stdout 0 字节，stderr 0 字节**（两个流 hexdump 都是空的）。git 对整个改写过程一个字都不说。
  - `git cat-file -p :f.txt` → **4 字节** `610a 620a`，sha256 `911169ddaaf146aff539f58c26c489af3b892dff0fe283c1c264c65ae5aa59a2`，blob OID `422c2b7ab3b3c668038da977e4e93a5fc623169c`。**入库字节比工作树少 2**，工作树那份是 `58055bdcc73787eb88c78d36f0b4939e9c5dc1c3ad17e25cc85a6833cf1a0cab`。
  - commit 之后 `rm f.txt && git checkout -- f.txt` → 工作树又变回 **6 字节** `58055bdc…`，git 把 CR 原样加回来（双向转换）。
  - 就在这一瞬间：`git status --porcelain` **0 行 / 0 字节**、`git diff --stat` 空、`git diff HEAD --stat` 空，三者退出码全 0；而 `cmp <blob> <工作树文件>` → `differ: byte 2, line 1` **退出码 1**，`sha256sum --status` → **退出码 1**。
  - **这就是失效层**：git 侧一切"内容相同"的信号都报相同，字节层一切信号都报不同。**任何用 sha256 断言「仓库内容 == 本地文件」的校验（发布前核对资产、agent 自检同步是否成功、CI 比对打包产物）在这个配置下必然假不等**，而且 git 会反过来告诉你"你没改动"。与 `shell-quoting-and-path-forms §10` 同族——那边是命令替换剥掉尾部 `\n`，这边是 git 转换层吃掉/吐出 `\r`，表象都是"只差行尾几个字节的不等"。区别：`shell-quoting-and-path-forms §10` 那侧差值恒为 1 字节且单向，本条差值 = CR 个数（实测 2）且 checkin/checkout 双向。
- **根因**：行尾转换发生在 **checkin/checkout 的转换管道**里，`git status` 比的是"套完转换规则之后"的内容，所以它和工作树永远一致；`cmp`/`sha256sum` 比的是磁盘原始字节。两者看的是不同的东西，不是谁出错。
  本机现状（只读取证）：`git config --list --show-origin | grep -i -E 'autocrlf|safecrlf|eol'` **只输出一行** `file:<Git 安装目录>/etc/gitconfig	core.autocrlf=true`——Git for Windows 的 **system 级默认**。`git config --global --get core.autocrlf` 与 `--local --get` **退出码都是 1（未设）**，`core.safecrlf` 同样退出码 1。**没有人显式打开过它，它默认就是开的**，所以"我没配过"不是安全证据。
  `git ls-files --eol` 的三态字段（本仓库**全部**跟踪文件都是 `i/lf    w/lf    attr/text=auto eol=lf `+TAB+路径）：
  - `i/` = **索引里 blob 的形态**（实测到 `i/lf`、`i/crlf`；其余取值未测到）。
  - `w/` = **工作树磁盘文件的形态**（实测到 `w/lf`、`w/crlf`、`w/mixed`）。
  - `attr/` = 该路径解析到的 `.gitattributes` 规则；**`attr/` 后为空 = 没有任何属性命中，此时行为完全由 `core.autocrlf` 决定**——这就是危险态。
  - 实测取样四行：`i/lf    w/crlf  attr/`（清洗已发生）、`i/crlf  w/crlf  attr/`（blob 已被污染）、`i/lf    w/mixed attr/`（混合行尾）、钉死后 `i/lf    w/lf    attr/text=auto eol=lf`。**字段用空格补齐、路径前只有一个 `0x09` TAB**，而 `attr/` 的值里本身含空格 → **按空格 split 会切碎，要按 TAB 切**。
- **对策**：
  1. **钉死（唯一真解）**：`.gitattributes` 写一行 `* text=auto eol=lf`（19 字节，它自己要以 LF 落盘）。实测加钉后新建的 6 字节 CRLF 文件：blob 4 字节 → commit + `rm` + `git checkout --` → 工作树 4 字节 → `cmp` **退出码 0**、与工作树 sha256 完全相同。**而且 `add` 不再沉默**：stderr **98 字节** `warning: in the working copy of 'g.txt', CRLF will be replaced by LF the next time Git touches it`（退出码仍 0）。同一个动作，无钉 **0 字节**、有钉 **98 字节**——这就是"静默"与"不静默"的可测分界。
  2. **钉不追溯**（必须补一刀）：加 `.gitattributes` 后，**已跟踪文件一个字节都不会被动**。实测加钉那一刻 `f.txt` 仍是 `i/lf w/crlf`、工作树仍 6 字节、`git status --porcelain` 仍干净。要真对齐必须再来一次 checkout（实测 `rm` + `git checkout -- f.txt` 即从 6→4 字节，`cmp` 退出码 0）。
  3. **已经污染过**（blob 里已带 CR，即 `i/crlf`）：`git add --renormalize .`。实测在"注入 `core.autocrlf=false` 造成 `i/crlf w/crlf attr/`、HEAD blob 6 字节 OID `c30dea8a3641ea99b125d04d599d843712292759`"的仓库上：命令**退出码 0、stdout/stderr 各 0 字节**，索引里的 blob 变 4 字节、`ls-files --eol` 变 `i/lf w/crlf attr/text=auto eol=lf`、`git status --porcelain` 出现 `M  h.txt`；**HEAD 的 OID 要到下一次 commit 才变**（→ `422c2b7a…`）。**两条实测边界**：① 它只重写**索引/blob**，工作树字节原封不动（仍 6 字节）；② 它**不会 stage 新文件**——`.gitattributes` 自己在 renormalize 之后仍是 `?? .gitattributes`，必须单独 `git add .gitattributes`。
  4. **把沉默变成硬报错（半个网）**：注入 `core.safecrlf=true` 后 add 一个混合行尾文件（12 字节 `610d 0a62 0a63 0d0a 640a 650a`，`a`/`c` 两行 CRLF + `b`/`d`/`e` 三行 LF）→ **退出码 128**，stderr **45 字节** `fatal: LF would be replaced by CRLF in m.txt`，**索引里什么都没有**（`git ls-files -s` 空），文件退回 `?? m.txt`。`core.safecrlf=warn` 退化成退出码 0 + 98 字节 warning。对照组（不加 safecrlf，只靠默认 `autocrlf=true`）同一个混合文件：退出码 0、stderr 98 字节 `warning: in the working copy of 'm.txt', LF will be replaced by CRLF the next time Git touches it`、blob 被洗成 10 字节全 LF。
     **safecrlf 不是解药**（实测对照）：`core.safecrlf=true` + **纯 CRLF** 文件 → add **退出码 0、stdout/stderr 均 0 字节**，blob 照样被洗成 4 字节。它只在"转换不可逆"时叫；行尾一致的正常清洗全程静默。要挡只有对策 1。
  5. **做实验不要动 git 配置**：`GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.autocrlf GIT_CONFIG_VALUE_0=false git add …`（`--show-origin` 里显示成 `command line:	core.autocrlf=false`），或内联 `git -c <key>=<val> <子命令>`（`-c` 必须在子命令之前，见 `git-ref-plumbing-on-windows §8`）。
- **判定**：贴这两行进终端，回答"这个仓库在我这台机器上会不会静默改我 push 的字节"：
  ```bash
  cd "<盘符>\<项目>"
  git config --get core.autocrlf; git check-attr text eol -- .
  ```
  读值（三条分支，实测都跑通过）：
  - 打 `true`（或 `input`）**且** `check-attr` 打 `text: unspecified` / `eol: unspecified` → **确诊危险**：下一次 `git add` 会静默改字节，且 stdout/stderr 都是 0 字节。实测未钉的 scratch 仓库正是这一组。
  - `check-attr` 打 `text: auto` + `eol: lf` → **确诊安全**：行尾由仓库钉死，跨机器一致，`add` 会给 98 字节 warning 而不是沉默。实测本仓库与钉死后的 scratch 都是这一组。
  - `core.autocrlf` 无输出、退出码 1 → checkin 侧不改，**但不等于安全**（工作树仍可能被 `.gitattributes` 或队友已污染的 blob 影响），继续跑下面两条审计。
  - 附：`git check-attr` 对不存在的路径照样解析、退出码 0，所以**不必先找真文件**（实测 `git check-attr text eol -- no/such/path.md` 在两种仓库里都退 0）；但**那两个字段的值是仓库性质，不是路径性质，别照抄数字**：2026-09-18 同一条命令对照跑，本仓库（`* text=auto eol=lf` 已钉）打 `text: auto` / `eol: lf`，未钉的 scratch 仓库打 `text: unspecified` / `eol: unspecified`。**读上面三条分支时先认这台机器的仓库钉没钉**——在未钉仓库里跑出一条路径得到 `unspecified`，那是分支 1 的**正确确诊输入**，不是你命令写错了。`-- .` 也可直接用。
  再补两条**互补**审计（各自覆盖对方的盲区，只做第一条会漏）：
  ```bash
  git ls-files --eol | grep -vE '^i/([a-z]+)[[:space:]]+w/\1'          # 退出码 1=全部一致 / 0=至少一个文件工作树形态≠索引形态
  git ls-files -z | while IFS= read -r -d '' p; do
    a=$(git cat-file blob "HEAD:$p" | wc -c); b=$(git cat-file blob "HEAD:$p" | tr -d '\r' | wc -c)
    [ "$a" != "$b" ] && echo "BLOB_HAS_CR $p $((a-b)) $a"
  done
  ```
  实测第二条在未钉仓库打出 `BLOB_HAS_CR j.txt 2 6`（该文件是 `i/crlf w/crlf`，**第一条 grep 看不见它**，因为两侧形态"一致"）；本仓库上第一条退出码 1（无形态不一致）、第二条空输出（无 blob 含 CR），**两条各自为真才算安全**。
  **三个现场踩到的坑**：① 反引用**必须写在单引号里**。写成 `$'^…w/\1'` 会被 bash 当八进制转义吃掉，模式里变成一个 `0x01` 字节，反引用永不匹配 → `grep -v` **把所有行都吐出来且退出码 0**，一眼看去像"全仓库每个文件都被改了"（实测：同一命令在干净的本仓库上，单引号版退出码 1/0 行输出，`$'…'` 版退出码 0/把跟踪文件全列出来）。② `grep` 的退出码方向和"有没有问题"是**反的**（0=匹配到=有问题，1=没匹配到=安全），别按 `silent-failure-triage §1` 的直觉读。③ **`git ls-files --eol` 不能按空白切列**：它的 `attr/` 字段自身含空格、文件名前是一个 TAB。实测字段数分布——本仓库（已钉 `* text=auto eol=lf`）**16 行全是 5 段**（`attr/text=auto` + `eol=lf` 被切开），未钉的 scratch 仓库 `attr/` 为空、**4 段**。所以 `awk '{print $3}'` 在钉过的仓库拿到的不是文件名、在未钉仓库拿到 `attr/`，同一个列号两种仓库指向不同东西；而"未钉"那种恰好不碎，**测试样本会骗人**。要取列就用锚定正则（如上面那条 `^i/…` 的写法）或 `-z` 后自己按最后一个 TAB 切。
- **验证于**：Windows 10.0.26200.0（`cmd /c ver` 报 10.0.26200.9457）· Git Bash `GNU bash 5.2.37(1)-release (x86_64-pc-msys)` · git 2.53.0.windows.2 · zh-CN / ACP 936（`[Text.Encoding]::Default` = `gb2312`）· 2026-09-17 首发 · 2026-09-18 独立复跑：机制结论三条分支全部一致，但**两处读数被证明是仓库性质而非普适答案**（`check-attr` 对不存在路径的取值在未钉仓库是 `unspecified/unspecified`；`ls-files --eol` 字段数 5 段 vs 4 段），已在正文分别注明，别照抄数字。

## 8. 「默认编码」按客户端各定各的：拿到命令先走五岔链，**退出码不参与判定**

- **现象**（中文 Windows 实测，ACP/OEMCP 均 936）：同一句 `中文测试` 交给四个客户端落盘，落成**三种编码**，**四条命令退出码全为 0**（长度取 `stat -c %s`，字节取 Git Bash 自带 `xxd`）：
  ```bash
  printf '中文测试\n' > a.txt                                  # 13 B  e4 b8 ad e6 96 87 e6 b5 8b e8 af 95 0a      无 BOM UTF-8 + LF
  powershell -Command "'中文测试' | Out-File b.txt"             # 14 B  ff fe 2d 4e 87 65 4b 6d d5 8b 0d 00 0a 00  UTF-16LE + BOM
  powershell -Command "Set-Content -Path c.txt -Value '中文测试'" # 10 B  d6 d0 ce c4 b2 e2 ca d4 0d 0a             GBK/cp936（无 BOM）
  MSYS_NO_PATHCONV=1 cmd /c "echo 中文测试 > d.txt"              # 11 B  d6 d0 ce c4 b2 e2 ca d4 20 0d 0a           同上 GBK，外加 echo 把 `>` 前那个空格也写进去
  ```
  读侧同样各说各话，而且**大多不报错**：`Get-Content c.txt -Encoding UTF8 | Out-File -Encoding utf8 c_fix.txt` 全程 exit 0，那 4 个汉字变成 6 个 U+FFFD + 1 个 `Ĳ`（10 B → 25 B），再落一次 ANSI 只剩 `3f 3f 3f 3f 3f 3f 3f`——原文永久没了；`node -e` 以默认 `utf8` 读同一个 GBK 文件也 exit 0、静默塞 U+FFFD；只有 Python `open('a.txt')` 抛 `UnicodeDecodeError: 'gbk' codec can't decode byte 0xad in position 2`（exit 1）——**但同一份代码读 UTF-8 的 `你好世界` 却 exit 0 解出 `浣犲ソ涓栫晫`**。同机器两套运行时给出相反默认值：`locale.getpreferredencoding(False)=cp936` 对 `Buffer.from('中文测试').length=12`。
- **根因**：编码不是文件的属性，是**每个客户端各自的默认值**，而这台机器上这些默认值来自六处、互不相同，且没有任何一层会提示你它替做了决定：bash 侧恒 UTF-8 且与 `LANG` 无关（`LANG=C LC_ALL=C printf` 落盘仍是 `e4 b8 ad…`）；PowerShell 里 `Out-File`/`>` 与 `Set-Content` 的默认**方向相反**；PS 喂原生命令 stdin 另走 `$OutputEncoding`（本机 `us-ascii`）；Python 一条 `import` 里四个"默认"三种答案（`utf-8` / `utf-8` / `cp936` / `gbk`）；Node 恒 `utf8`，`LANG=zh_CN.GBK` 改不动。两个专坑检索与查文档的细节：`[Text.Encoding]::Default` 的 `CodePage=936` 但 `WebName` 报 **`gb2312`**（按 `gbk` grep 搜不到它）；`Set-Content` 本机实测落 GBK（俄文字母 → `a7 a7`，emoji 代理对的两半各降级为一个 `3f`，若真按某些文档说的默认 ASCII 则中文应是全 `3f`），而 `Get-Help Set-Content -Parameter Encoding` 的 `defaultValue` 取回**空**——**默认值只能实测，文档和帮助窗口都会给假答案**。
- **对策**：① 写侧统一"无 BOM UTF-8"，并按客户端挑工具：bash 直接重定向即可；PowerShell 用 `[IO.File]::WriteAllText($p,$s,(New-Object System.Text.UTF8Encoding($false)))`——实测 5.1 的 `-Encoding utf8`（`Out-File` 与 `Set-Content` 都一样）必带 `ef bb bf`，17 B；Python 显式 `encoding=`（见 python-silent-data-errors §1）；Node 的 `fs.writeFileSync(p,s,'utf8')` 本就落 UTF-8 + LF。② **别指望 `chcp 65001` 能修文件**：实测改完码页后 `Set-Content` 仍落 `d6 d0 ce c4…`、`[Text.Encoding]::Default.CodePage` 仍 936，它只动显示层（见 `windows-text-encoding §3`）。③ **别给单条命令顺手加 `PYTHONUTF8=1`**：实测 `python p1.py | Out-File` 不加得到 UTF-16 里正确的 `中文测试`（14 B），加了得到 18 B 的 6 字符乱码（实测第 2 个字符落在私用区 U+E15F，终端里显示不出来、也没法再编回 GBK）——Python 改吐 UTF-8 字节而 PowerShell 仍按 936 解；要设就整条链一起设。④ 跨 PS→原生命令的管道先 `$OutputEncoding=[Text.Encoding]::UTF8`，实测默认值下 `'中文测试' | python -c "…sys.stdin.buffer.read()…"` 进原生 stdin 的字节就是 `3f 3f 3f 3f`（两侧 exit 0），设完则 stdin 头三字节是 `ef bb bf`（5.1 连管道都加 BOM），读侧按 `utf-8-sig` 打底（见 python-silent-data-errors §7）。⑤ 资产层统一约定见 `windows-text-encoding §5`，本节只解决"先弄清这台机器每个客户端会怎么选"。
- **判定**：30 秒定死"这条命令会用哪个编码"，五岔顺序取读数，**每岔只看读数、不看退出码**：
  ```bash
  # 岔 1｜底座：这台机器的"默认 ANSI"到底是哪个 ANSI
  chcp.com                                                      # → 936。这行输出本身就是 GBK 字节（实测 bb ee b6 af…），被 UTF-8 捕获层显示成乱码 = `windows-text-encoding §3` 的活教材
  powershell -NoProfile -Command "[Text.Encoding]::Default.CodePage"   # → 936（WebName=gb2312，同物两名）
  locale charmap                                                # → UTF-8。bash 与上面两个无关，改 LANG 也不变
  # 岔 2｜写方：命令行里出现哪个名字，就用哪个默认（同一条 -Command 里可以两种都有）
  #   Out-File / `>` → UTF-16LE+fffe ｜ Set-Content / Add-Content / -Encoding default|oem → 系统 ANSI
  #   -Encoding utf8 → UTF-8 但必带 efbbbf ｜ bash 重定向 → 字节透明（程序写什么落什么）
  # 岔 3｜边界：跨进程几次就重编码几次，先取这两个读数
  powershell -NoProfile -Command "\$OutputEncoding.WebName;[Console]::OutputEncoding.CodePage"   # → us-ascii / 936
  # 岔 4｜读方：同机器两套相反答案（Get-Content 的默认另见 `windows-text-encoding §2`）
  #   ⚠ 取这四个值之前先读一个前置量，否则拿到的可能不是"这台机器的默认值"而是宿主注入的结果：
  python -c "import sys;print('utf8_mode=',sys.flags.utf8_mode)"   # 0=原生默认；1=有 PYTHONUTF8/PYTHONIOENCODING/-X utf8 覆盖
  python -c "import sys,locale;print(sys.getdefaultencoding(),sys.getfilesystemencoding(),locale.getpreferredencoding(False),sys.stdout.encoding)"   # → utf-8 utf-8 cp936 gbk
  node -e "console.log(Buffer.from('中文测试').length)"           # → 12；Node 侧恒 UTF-8，不受 ACP 影响
  # 岔 5｜字节验收（唯一有效判据）
  python -X utf8 -c "import sys;b=open(sys.argv[1],'rb').read();g=lambda e:b.decode(e,'replace')==b.decode(e,'ignore');print('%-12s len=%-4d head=%-23s utf8=%-5s gbk=%-5s hasFFFD=%s'%(sys.argv[1],len(b),b[:8].hex(' '),g('utf-8'),g('gbk'),chr(0xfffd) in b.decode('utf-8','ignore')))" <文件>
  ```
  期望读数（本机实测，缺一即命中）：无 BOM UTF-8 `utf8=True gbk=False`；GBK `utf8=False gbk=True`；UTF-16LE `utf8=False gbk=False` 且 `head=ff fe…`（**UTF-16 只认 BOM**——偶长字节丢给 `utf-16` 一定"解得开"，实测把 GBK 文件按 utf-16 解会出 `탖쓎…`，参与投票必误判）。两条阶梯查不出来的情况要记住：`utf8=True hasFFFD=True` 是"**已经坏了但能解**"（`c_fix.txt` 就是这样），一旦 `hasFFFD` 为真就别再往这个文件写任何东西；`head=3f 3f 3f 3f` 是"中文已被替换成问号"，它是合法 ASCII，阶梯两头都 True，只能靠"写方是谁"+ 与已知好的字节对比发现。`?`/U+FFFD 一旦出现即不可逆：实测把那条 `PYTHONUTF8=1` 产出的 mojibake 串（13 B 的 UTF-8 源文件变成 18 B 的 UTF-16 乱码文件）拿 `.encode('gbk')` 想还原，会先撞 `UnicodeEncodeError: '\ue15f' illegal multibyte sequence`。**退出码不能当编码判据**——同一类 UTF-8 中文，Python 默认读 `中文测试` 抛异常 exit 1、读 `你好世界` 静默 exit 0；何况管道还会让 `$?` 说谎（见 silent-failure-triage §1）。
  **岔 4 前置量为什么必须先读**：`utf8_mode=1` 时（宿主注入 `PYTHONUTF8=1` 或 `PYTHONIOENCODING=utf-8`，agent / IDE / CI 三类宿主都常见）上面那四个值会整体变成 `utf-8 utf-8 utf-8 utf-8`，**并且"用默认编码读 UTF-8 中文抛异常"这条现象直接消失**——实测同一份文件、同一句代码：`utf8_mode=0` 抛 `UnicodeDecodeError: 'gbk' codec can't decode byte 0xad in position 2` 退 1，`utf8_mode=1` 退 0 且内容正确。照抄"全 utf-8"的读数会得出**"这台机器没有 GBK 问题"的反向结论**，而它只说明当前这个 Python 进程被环境变量接管了。
  但**反过来也不成立：`utf8_mode=0` 不等于拿到了原生默认值**。实测三行对照（同一条 `-c` 打印 `utf8_mode` + 四个编码值，Python 3.12.10）：

  | 环境变量 | 读数 |
  |---|---|
  | `PYTHONUTF8=1 PYTHONIOENCODING=utf-8` | `1 utf-8 utf-8 utf-8 utf-8` |
  | `env -u PYTHONUTF8 -u PYTHONIOENCODING` | `0 utf-8 utf-8 cp936 gbk` ← 这才是本机原生值 |
  | 只 `env -u PYTHONUTF8`（留着 `PYTHONIOENCODING`） | `0 utf-8 utf-8 cp936 `**`utf-8`** |

  第三行是新的假阴性来源：`PYTHONIOENCODING` **单独**就能把第四个值抬成 `utf-8`，而**不会**把 `utf8_mode` 置 1。所以别只读一个 `utf8_mode` 就宣布"没被接管"——**岔 4 的完整读数是 `utf8_mode` + `PYTHONUTF8`/`PYTHONIOENCODING` 两个变量在不在**三者一起记，只记四个编码值不足以复现，只记 `utf8_mode` 也不足。清干净再取原生值：`env -u PYTHONUTF8 -u PYTHONIOENCODING python -c "…"`（实测逐字复现原文四值）。
  本机可用工具边界（判定链依赖它们）：`iconv`/`jq`/`bc`/`rev`/`pwsh` **都不存在**，所以"Git Bash 里一行转码"这条路直接不可用，跨码页转换只剩显式两端指定（Python `encoding=`，或实测可用的 `node -e "new TextDecoder('gbk').decode(...)"`，本机 Node 带全 ICU）；`file -b` 会把 GBK 报成 `ISO-8859 text`，不可信；取字节用 `xxd`（Git Bash）或 `Format-Hex`（仅 PowerShell 内）。另注意 `python3` 在本机是 0 字节 App Execution Alias 壳（`--version` 零输出、**exit 49**——这个数还随"谁在读"变，PowerShell / Node / `.bat` 内 `ERRORLEVEL` 读到的是 **9009**，见 `runtime-resolution-and-abi §1`；`Length=0` + `ReparsePoint` 同节），`py -3` 指向一个不存在的路径、**exit 101**，且它报错末尾那串 `?` 是**生产端就已经写出的 `3f` 真字节**、不是显示层（见 runtime-resolution-and-abi §2）——所以本节所有 Python 读数都是用 PATH 里第一个真解释器（3.12.10）取的。调 `cmd` 取"第三个客户端"的读数时也别裸写 `cmd /c "…"`：MSYS 会把 `/c` 当路径重写掉，结果起了个交互式 cmd、**照样 exit 0** 且一个文件都没落（实测），必须加 `MSYS_NO_PATHCONV=1`（见 shell-quoting-and-path-forms §7）。
- **验证于**：Windows 11 家庭版 中文版 10.0.26200.9457（zh-CN，ACP=OEMCP=936，`Get-Culture`/`Get-WinSystemLocale`/`Get-UICulture` 均 zh-CN，注册表 `Nls\CodePage` 的 ACP/OEMCP 都 936 = 没开系统级 UTF-8） · Git Bash 5.2.37(1)-release(x86_64-pc-msys) / MINGW64_NT-10.0-26200 / MSYS 3.6.6，本会话 `LANG`/`LC_ALL=C.UTF-8` 为父进程注入（`env -u LANG` 后 Git Bash 自己给 `zh_CN.UTF-8`，两种取值下 `printf` 落盘字节完全相同） · Windows PowerShell 5.1.26100.9444（本机无 pwsh 7） · Python 3.12.10（`<用户名>\AppData\Local\Programs\Python\Python312\python.exe`） · Node v24.18.0 · git 2.53.0.windows.2 · 2026-09-17 首发 · 2026-09-18 独立复跑：本会话 ambient **未**设 `PYTHONUTF8`/`PYTHONIOENCODING`（`utf8_mode=0`，四个值与原文逐字一致），上面那张三行环境变量对照表是当天新测；据此在岔 4 前加了前置量读数。

## 9. `.bat` 里的非 ASCII 注释：无 BOM 也照样坏——cmd 按 GBK 逐字节错位解析，注释残片被当成命令执行

- **现象**（本机实测，一次烧掉整轮自启动验收）：一个**无 BOM、UTF-8、内容语法全对**的 `run_daemon.bat`，注释行里含中文与 em-dash（`—`）。cmd 跑起来打出 `'-bridge' 不是内部或外部命令`、`TAIL: cannot open 'timestamp,'` 之类的错——**注释文本被执行了**，真正的启动命令根本没轮到，守护不启动，而外层重启循环还每 10 秒忠实地再撞一遍。
- **根因**：cmd 按**系统 ANSI 代码页（本机 cp936/GBK）逐字节**解析 `.bat`。UTF-8 的中文/全角破折号字节流（如 `e4 b8 ad`）喂给 GBK 解码器时，某些字节会被当作 **GBK 双字节词的前缀字节**，把后一个字节吞进来配成一个汉字——被吞的可能是 `\r` 或 `\n` 或下一条注释的首字节，于是**从那一行起解析窗口整段错位**：`::` 注释的行连接结构被破坏，注释残片落到"命令"的位置上被执行。与 §1 的 BOM 坑是**两个独立机制**：BOM 支坏在**首行**（`'﻿@echo' 不是命令`，一眼能定位）；本支坏在**任意非 ASCII 字节所在行及其后**，前面几十行都正常，看起来像"偶发语法错"。
- **对策**：`.bat` 一律 **纯 ASCII + CRLF**——注释也用英文写；要中文说明写进同目录的 `.md`，由 bat `echo` 一个英文提示指过去。从 bash/heredoc 生成 bat 的固定收尾：写完立刻 `sed -i 's/\r*$/\r/' file.bat`（补 CRLF，幂等），再跑一条 ASCII 断言（见判定）。这也解释了 §1 对策里"注释尽量纯 ASCII"那半句——它不是风格建议，是本条的预防措施。
- **判定**：落盘后、注册前，两条各 5 秒：
  ```bash
  grep -nP '[^\x00-\x7F]' run_daemon.bat        # 必须 0 命中；有输出即命中本条（哪怕只出现在注释里）
  od -An -tx1 run_daemon.bat | grep -c '0d 0a'  # >0 = CRLF 在；为 0 先补 sed 那条
  ```
  运行侧的确诊信号：cmd 报错文案里出现**你自己注释里的词**（本例 `'-'`、`'TAIL:'` 都来自注释句）⇒ 不是命令写错了，是解析错位，改文件编码形态而不是改命令。
- **验证于**：Windows 11 家庭中文版 10.0.26200（ACP=936）· cmd 10.0 · Git Bash 5.2.37 · 2026-09-19
  （实测：含中文+em-dash 注释的 bat 打出 `'-bridge' 不是内部或外部命令`；重写为纯 ASCII+CRLF 后同一台机同一任务正常拉起守护，日志尾部时间戳为证。未对"哪个字节序列必然吞换行"做逐字节复现——判定用上游 grep 即封死，不必依赖具体错位模式。）

## 10. 文本模式 `open()` 整文件读写：只想插几行，落盘却把全文件行尾翻译了一遍

- **现象**（本机实测，一次让五份镜像副本同时字节级冲突）：用 Python 往一份 LF 的共享 `SKILL.md` 里插 4 行，读写都只写了 `encoding='utf-8'`。改后字节数 14387 → **15772**（+1385 ≈ 行数），`CR` 计数 0 → **1438**（= 行数），`git diff` 显示"整个文件删除 + 整个文件新增"，而真实意图只是 +4 行；这份文件另有若干份由同步脚本扇出的镜像副本，于是一次插入变成五处逐字节不一致。用 `difflib` 按行比对却"看不出内容变了"——因为变的不是内容，是行尾。
- **根因**：Python 文本模式有**两道默认翻译，都不报错**：读侧 universal newlines 把盘上的 `\r\n` 折成内存里的 `\n`，写侧再按平台默认（Windows 的 `os.linesep` = `\r\n`）把 `\n` 翻译回去。所以"读→改一小段→写"这条最自然的写法，等价于**把整个文件按当前平台的行尾重新编码一遍**。与 §7 同类但在另一头：§7 是 git 在 `add` 时按 `core.autocrlf` 转换（工作树字节 ≠ blob 字节，`git status` 还说干净），本条是**编辑进程自己**当场改了盘上字节，git 会老实报"整文件变更"。与 python-silent-data-errors §2（`csv.writer` 漏 `newline=''` 导致每行后多一个空行）同一机制、不同症状：那条只影响"库自己已经写了 `\r\n`"的场合，本条影响任何整文件读写。
- **对策**：整文件改写一律**显式钉死行尾**——读 `open(f, encoding='utf-8', newline='\n')`（或 `newline=''` 干脆不翻译），写 `open(f, 'w', encoding='utf-8', newline='\n')`；或走二进制 `read_bytes`/`write_bytes`，只在字节层做替换。能用"只替换目标串"的语义化编辑工具就别重写整个文件。共享文件改前必备份，改后必须过下面那两条判定再说完成。
- **判定**（各一秒，别靠肉眼看 diff）：
  ```bash
  tr -dc '\r' < SKILL.md | wc -c   # 改前改后必须同一读数（本机这批共享 md 全是 0）
  wc -c < SKILL.md                 # 增量应等于"你想插的字节数"，不是整文件大小
  ```
  两条任一不对即命中本条：还原备份，加 `newline='\n'` 重跑。参照实测：第一遍 CR=0→1438、字节 +1385；改成 `newline='\n'` 后同一插入为 **CR 仍 0、+4 行 / −0 行**，与镜像副本重新一致。
- **验证于**：Windows 11 家庭中文版 10.0.26200（ACP=936）· Python 3.12.10 · Git Bash 5.2.37 · 2026-09-19（六份共享 `SKILL.md` 批量插入那一轮：第一遍全文件 CRLF 化，从备份还原后改 `newline='\n'` 重跑，逐份核对 CR=0 与 +4/−0）。

## 复用信号
"改完脚本没生效""只有中文出错""同一文件我看得懂下游看不懂""读到一串问号""解码没报错但内容是乱的" → 一律先取字节再看，别在文本层推理。
- "只想加两行、diff 却把整个文件划掉了""改完几份镜像副本全说内容不同""按行 diff 看不出变化但字节数涨了" → §10（文本模式 `open()` 自己翻译了整文件行尾，落盘前后必须比 CR 数与字节增量）。
- "本地文件哈希和仓库 blob 哈希对不上、但 `git status` 说干净""clone 出来的文件字节数和上游不一样""`git add` 一个字没说、push 上去的内容却变了""`i/lf w/crlf` 这种字段看不懂" → §7（`core.autocrlf` 在转换管道里静默重写行尾，git 侧信号全部报"相同"）。
- "同一句话在 bash 里是 UTF-8、在 PowerShell 里变 UTF-16、在 Set-Content 里变 GBK""退出码 0 但中文成了问号""Get-Content 读回来再写回去就坏了" → §8（默认编码是每个客户端各自的默认值，退出码不参与判定）
