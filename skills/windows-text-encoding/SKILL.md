---
name: windows-text-encoding
description: Windows 文本编码与 BOM 判定手册。写/改 PowerShell 脚本、批处理 .bat、含中文的数据文件、脚本"运行成功但输出乱码"、读别人给的文件出现替换字符之前读。触发词：乱码、编码、BOM、efbbbf、UTF-8 读坏、GBK、cp936、chcp、Get-Content、解析器报 invalid start byte、中文变问号、脚本改完不生效。
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

## 复用信号
"改完脚本没生效""只有中文出错""同一文件我看得懂下游看不懂""读到一串问号""解码没报错但内容是乱的" → 一律先取字节再看，别在文本层推理。
