---
name: windows-text-encoding
description: Windows 文本编码与 BOM 判定手册。写/改 PowerShell 脚本、批处理 .bat、含中文的数据文件、脚本"运行成功但输出乱码"、读别人给的文件出现替换字符之前读。触发词：乱码、编码、BOM、efbbbf、UTF-8 读坏、GBK、cp936、chcp、Get-Content、解析器报 invalid start byte、中文变问号、脚本改完不生效、行尾被改写、CRLF、autocrlf、git ls-files --eol、i/lf w/crlf、哈希对不上但 git status 干净。
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
  head -c 3 a.ps1 | xxd   # 期望 45fbb… 即 efbbbf
  head -c 3 a.bat | xxd   # 期望不是 efbbbf
  ```
  PowerShell 侧：`[IO.File]::ReadAllBytes($p)[0..2]`。

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
  - 附：`git check-attr` 对不存在的路径照样解析（实测 `git check-attr text eol -- no/such/path.md` → `text: auto` / `eol: lf`，退出码 0），所以不必先找真文件；`-- .` 也可直接用。
  再补两条**互补**审计（各自覆盖对方的盲区，只做第一条会漏）：
  ```bash
  git ls-files --eol | grep -vE '^i/([a-z]+)[[:space:]]+w/\1'          # 退出码 1=全部一致 / 0=至少一个文件工作树形态≠索引形态
  git ls-files -z | while IFS= read -r -d '' p; do
    a=$(git cat-file blob "HEAD:$p" | wc -c); b=$(git cat-file blob "HEAD:$p" | tr -d '\r' | wc -c)
    [ "$a" != "$b" ] && echo "BLOB_HAS_CR $p $((a-b)) $a"
  done
  ```
  实测第二条在未钉仓库打出 `BLOB_HAS_CR j.txt 2 6`（该文件是 `i/crlf w/crlf`，**第一条 grep 看不见它**，因为两侧形态"一致"）；本仓库上第一条退出码 1（无形态不一致）、第二条空输出（无 blob 含 CR），**两条各自为真才算安全**。
  **两个现场踩到的坑**：① 反引用**必须写在单引号里**。写成 `$'^…w/\1'` 会被 bash 当八进制转义吃掉，模式里变成一个 `0x01` 字节，反引用永不匹配 → `grep -v` **把所有行都吐出来且退出码 0**，一眼看去像"全仓库每个文件都被改了"（实测：同一命令在干净的本仓库上，单引号版退出码 1/0 行输出，`$'…'` 版退出码 0/把跟踪文件全列出来）。② `grep` 的退出码方向和"有没有问题"是**反的**（0=匹配到=有问题，1=没匹配到=安全），别按 `silent-failure-triage §1` 的直觉读。
- **验证于**：Windows 10.0.26200.0（`cmd /c ver` 报 10.0.26200.9457）· Git Bash `GNU bash 5.2.37(1)-release (x86_64-pc-msys)` · git 2.53.0.windows.2 · zh-CN / ACP 936（`[Text.Encoding]::Default` = `gb2312`）· 2026-09-17

## 复用信号
"改完脚本没生效""只有中文出错""同一文件我看得懂下游看不懂""读到一串问号""解码没报错但内容是乱的" → 一律先取字节再看，别在文本层推理。
- "本地文件哈希和仓库 blob 哈希对不上、但 `git status` 说干净""clone 出来的文件字节数和上游不一样""`git add` 一个字没说、push 上去的内容却变了""`i/lf w/crlf` 这种字段看不懂" → §7（`core.autocrlf` 在转换管道里静默重写行尾，git 侧信号全部报"相同"）。
