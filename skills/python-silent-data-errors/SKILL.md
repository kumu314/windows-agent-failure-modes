---
name: python-silent-data-errors
description: Windows 上用 Python 读写数据时那些"不报错、结果却是错的"失效模式。跑数据分析/清洗脚本、把结果交给下游读、Excel/CSV 往返、"我明明没报错怎么数字不对"之前读。触发词：pandas、read_csv、read_excel、to_excel、NaT、NaN、dtype object、清洗没生效、空行、多出来一行、\r\r\n、invalid start byte、编码没设 encoding、日期解析不出来、版本升级后结果变了、DirEntry.stat 的 ino 恒为 0、inode 去重塌成 1、遍历少算体积。
agent_created: true
---

# Python 数据读写的静默错误

一句话原则：**这类失效的共同点是"操作成功"**——退出码 0、无异常、文件也在。区别只在于内容对不对，所以每条都要有"取回真实字节/真实 dtype"的判定动作，而不是看日志有没有红字。

## 1. `open(p, 'w')` 不写 encoding：Windows 上默认不是 UTF-8

- **现象**（本机实测）：`open(p,'w')` 写入含中文的行，**不抛任何异常**；再用 `encoding='utf-8'` 打开就 `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xc3 in position 0: invalid continuation byte`。用 `encoding='gbk'` 能正常解出原文。
- **根因**：不写 encoding 时走 `locale.getpreferredencoding(False)`，中文 Windows 上是 **cp936**。写侧永远成功，坏在下一个消费者。
- **对策**：**所有** `open()` 显式带 `encoding='utf-8'`（写）/ `'utf-8-sig'`（读，顺带吃掉别人加的 BOM）。判据别靠肉眼看终端——终端可能是 GBK 控制台，好文件也显示成乱码，坏文件也显示得通。
- **判定**：
  ```bash
  python -c "import locale;print(locale.getpreferredencoding(False))"     # cp936 = 命中默认值陷阱
  python -c "open(p,'rb').read().decode('utf-8')[:40]"                    # 抛异常 = 文件真不是 UTF-8
  ```
  同一失效也解释"我的脚本在同事 Linux 上跑结果不一样"：**默认编码随机器变，显式编码不随机器变**。
- **复测环境交互（2026-09-18）**：本机设了 `PYTHONUTF8=1`（另有 `PYTHONIOENCODING=utf-8`）⇒ `sys.flags.utf8_mode=1`、`getpreferredencoding(False)` 报 **utf-8**，本节陷阱**不复现**。判定前先跑 `python -c "import sys;print(sys.flags.utf8_mode)"` 钉住这一点；要复现 cp936 一侧用 `python -X utf8=0`（实测报 **cp936**，写出的中文变 GBK 字节 `b'\xd6\xd0\xce\xc4\xb2\xe2\xca\xd4'`、utf-8 读侧 `UnicodeDecodeError`）。环境变量的完整分叉见 windows-text-encoding §8。
- **验证于**：Windows 11 家庭中文版 10.0.26200 · Git Bash 5.2.37 · python 3.12.10 · 2026-09-18

## 2. `csv.writer` 不加 `newline=''`：每一行后面多一个空行

- **现象**（本机实测）：`open(p,'w')` + `csv.writer` 写出的字节是 `b'a,b\r\r\n1,2\r\r\n'`（多了一个 `\r`）。按文本读回来是 `'a,b\n\n1,2\n\n'`——**每条记录之间都夹一个空行**，`splitlines()` 里出现空条目。行数、报表统计、"是否有数据"的判断全被带偏，且没有任何一方报错。
- **根因**：文本模式把 `\n` 翻译为 `\r\n`，而 csv 自己已经写了 `\r\n` → 双重翻译。
- **对策**：写 `open(p,'w',newline='',encoding='utf-8')`；读 `open(p,newline='',encoding='utf-8-sig')`。
- **判定**：`open(p,'rb').read()` 看真实字节里有没有 `\r\r\n`。有，就是这一条；不要靠"看起来行数对了"。
- **验证于**：Windows 11 家庭中文版 10.0.26200 · Git Bash 5.2.37 · python 3.12.10 · 2026-09-18
- **复测确认（2026-09-18）**：文本模式写两行 CSV 后真实字节为 `b'a,b\r\r\n1,2\r\r\n'`——`\r\r\n` 命中，原结论成立。

## 3. `dtype == object` 判断在新版 pandas 上永远为假

- **现象**：清洗脚本跑完，`strip()` / 全角转半角 / 空串归一 一个都没生效，但**没有任何报错**。同一份代码在一台机器有效、另一台无效。
- **根因**：pandas 3.x 起字符串列不再是 `object` dtype，`if df[c].dtype == object:` 恒为 False，整段清洗被跳过；2.x 上它是对的。所以这类 bug 只在"换环境"时暴露，本地怎么测都好。
- **对策**：用类型谓词，别比 dtype 常量：
  ```python
  from pandas.api import types as pdt
  if df[c].dtype == object or pdt.is_object_dtype(df[c]) or pdt.is_string_dtype(df[c]): ...
  ```
- **判定**：`print(repr(df[c].dtype), pd.__version__)` 一行就把环境钉死。**任何"清洗没生效"先跑这行**，别看代码逻辑。
- **验证于**：Windows 11 家庭中文版 10.0.26200 · Git Bash 5.2.37 · python 3.12.10 · pandas 3.0.5 · 2026-09-18
- **复测确认（2026-09-18）**：pandas 3.0.5 上 `pd.Series(['a','b']).dtype` 为 `<StringDtype(storage='python', na_value=nan)>`，`== object` **False**、`is_object_dtype` False、`is_string_dtype` True——原结论成立。

## 4. 混格式日期列：第一种格式胜出，其余静默变 `NaT`

- **现象**：一列里混着 `2026/1/3` 与 `2026-01-15`，`pd.to_datetime(col, errors='coerce')` 后后者全变 `NaT`；不抛错，只是数据少了。
- **根因**：`to_datetime` 一旦推断出格式就锁死它；`errors='coerce'` 又把"解析失败"从异常降格成缺失值。中文日期（`2026年1月16日`）与点分隔（`2026.1.3`）pandas 原生不认。
- **对策**：三步——① 先正则规整成统一形式（`2026年1月16日`/`2026.1.3` → `2026-01-16`/`2026-01-03`）；② `pd.to_datetime(s, errors='coerce', format='mixed')`，外面套 `except (TypeError, ValueError)` 兜住没有 `format='mixed'` 的老版本；③ 对"原始非空但解析后为空"的残余值逐个再试一次。
- **判定（关键，别省）**：算两个数并打印——`原始非空计数` 与 `解析后 notna 计数`。**只要不相等就是有值被 coerce 吃掉了**。顺带注意：coerce 后的 `NaT` 和本来就空的 `NaN` 不可分辨，所以这个差必须在 coerce 那一刻记下，事后无从追溯。
- **验证于**：Windows 11 家庭中文版 10.0.26200 · Git Bash 5.2.37 · python 3.12.10 · pandas 3.0.5 · 2026-09-18
- **复测确认（2026-09-18）**：`['2026/1/3','2026-01-15','2026年1月16日']` 直接 `to_datetime(errors='coerce')` ⇒ 原始非空 3 / 解析后 notna **1**（只剩第一种格式）；改 `format='mixed'` ⇒ 2（`2026年1月16日` 中文日期仍不认，需先按对策①正则规整）。原结论成立。

## 5. `to_excel` 写出去的全空行，`read_excel` 读不回来

- **现象**：造了带末尾空行的测试数据，"删除空行"功能怎么写都测不出来；测试全绿。
- **根因**：Excel 读回时末尾全空行会被丢掉——数据在写入环节就没了，与被测逻辑无关。
- **对策**：**测试用空行放中间，不放末尾**（夹在两条有内容的记录之间），或写完立刻断言行数与预期一致。
- **判定**：写完先读回来 `len(df)` 比一下，再生成断言。造数据这一步也要 round-trip，否则测的是"读取器的容忍度"。
- **验证于**：Windows 11 家庭中文版 10.0.26200 · Git Bash 5.2.37 · python 3.12.10 · pandas 3.0.5 · openpyxl 3.1.5 · 2026-09-18
- **复测确认（2026-09-18）**：中间空行 written 3 → read back **3**（保留）；末尾空行 written 4 → read back **2**（被丢掉）——原结论成立，测试数据造末尾空行等于白造。

## 6. `NaN` / 空串 / 字符串 `"nan"` 是三种不同的东西

- **现象**：`df[col].replace('', None)` 之后仍然"有空值"；`astype(str)` 之后 `NaN` 变成字符串 `"nan"`，参与唯一值统计、分组与文本匹配，且长度非 0、`if x:` 判真。
- **根因**：`astype(str)` 会把缺失值转成**看起来像数据的文本**，一旦做了这一步，缺失信息就永久丢失。
- **对策**：需要文本化时显式指定占位（`df[col].fillna('')` 再 `astype(str)`），并在归一化函数里把 `'nan'/'None'/'NaN'` 一并视为空；下游若按"非空即有效"过滤，就会把这三类字面量当真实值收下。
- **判定**：清洗前后各打印一次 `col.isna().sum()` 与 `(col.astype(str).str.strip()=='' ).sum()`，两个数都记下来；只记一个就无法区分"真没了"和"变成字符串了"。
- **复测环境差异（2026-09-18 · pandas 3.0.5）**：`pd.Series(['a',np.nan]).astype(str)` 后 NaN **保留为缺失值**（元素类型 str/float 混合、`isna().sum()` 仍为 **1**），**不再**变成字符串 `"nan"`——"NaN 被 astype(str) 变成 'nan' 文本"这一支在 3.x **不复现**；而字面量 `"nan"` 字符串仍是独立第三种值（前后都不 isna，会被"非空即有效"的过滤收下）。原结论按 2.x / object dtype 环境继续生效，两版并存。实测：`['a','',np.nan,'nan']` ⇒ `isna` 1、空串 1；`replace('', None)` 后 `isna` 升至 2。
- **验证于**：Windows 11 家庭中文版 10.0.26200 · Git Bash 5.2.37 · python 3.12.10 · pandas 3.0.5 · 2026-09-18

## 7. 写结果给别人读：把"我怎么写的"一起交付

- **现象**：本地 `df` 一切正常，对方拿到 CSV 后列错位、中文成 `??????`、多出一列空列（索引被写进去了）。
- **根因**：三类默认值共同造成——`to_csv` 未加 `encoding='utf-8-sig'`（Excel 双击打开时把 UTF-8 首列中文名解坏）、未加 `index=False`（多出一列无名索引）、以及 §1/§2 的编码与换行。
- **对策**：交付用 CSV 固定 `df.to_csv(p, index=False, encoding='utf-8-sig', newline='')`；Excel 用户为主才用 `utf-8-sig`（有 BOM 才认得出 UTF-8），纯程序消费用无 BOM UTF-8，并在交付说明里写清是哪一种。
- **判定**：`open(p,'rb').read(3)` 是 `b'\xef\xbb\xbf'` = 带 BOM；再看首行字节而不是看表格软件，表格软件会替你掩盖所有这些问题。
- **验证于**：Windows 11 家庭中文版 10.0.26200 · Git Bash 5.2.37 · python 3.12.10 · pandas 3.0.5 · 2026-09-18
- **复测确认（2026-09-18）**：`to_csv(encoding='utf-8-sig')` 首 3 字节 `b'\xef\xbb\xbf'`；`encoding='utf-8'` 首 3 字节 `b'\xe5\x88\x97'`（无 BOM）；不写 `index=False` 时首两行多出 `,列` / `0,1`——原结论全部成立。

## 8. 上面这些的元问题：环境不写在代码里就会漂

- **现象**：同一脚本昨天好、今天坏；`pip install` 装到了另一个解释器；`python -c "import x"` 通、`python x.py` 报 `ModuleNotFoundError`。
- **根因**：机器上并存多个解释器（安装包 Python、`py` 启动器注册的版本、uv/工具链自带的 Python、WindowsApps 别名）。`pip` 与 `python` 可以指向不同前缀。
- **对策**：**永远用 `python -m pip` / `<绝对路径>/python.exe -m pip`**，不用裸 `pip`；脚本首行打印 `sys.executable` + 关键库版本，把环境钉在输出里；长任务用绝对路径解释器（PATH 在不同 shell 里不一样，见 runtime-resolution-and-abi）。
- **判定**：
  ```bash
  python -c "import sys,pandas;print(sys.executable,pandas.__version__)"
  py -0p          # 列出启动器认为存在的全部版本
  ```
  `py -0p` 里出现的路径**可能根本不存在**（卸载残留的注册项），所以它只能当线索不能当结论——真正判据是 `<那个路径> -c "print(1)"` 的退出码。
- **验证于**：Windows 11 家庭中文版 10.0.26200 · Git Bash 5.2.37 · python 3.12.10 · pandas 3.0.5 · 2026-09-18
- **复测确认（2026-09-18）**：`py -0p` 列出 3 项（3.13、3.12*、uv 自带），其中 3.13 项路径执行 `-c "print(1)"` 实测**退出码 127**（路径不存在）、3.12 项退出码 0——"启动器列表含死路径"当场实证。

## 9. Windows 上 `DirEntry.stat(follow_symlinks=False)` 的 `st_ino` 恒为 0：按 inode 去重的递归会静默塌成 1 个

- **现象**（本机实测）：给递归扫描器加"用 `(st_dev, st_ino)` 做键、防目录循环"的防护，键取 `e.stat(follow_symlinks=False)`。结果：**同一个目录下的 6 个子目录拿到完全相同的键**（`dev=0, ino=0`），`if key in seen: continue` 把后续所有目录整体跳过。一次 192 个技能 / 221.76 MB / 1073 文件的盘点，被报成 **5.61 MB / 11 文件**——**无异常、无报错，只是数字小了 40 倍**；按它写出的报告会告诉你"这个目录几乎不占空间"。（本次是靠 `du -sh` 交叉核对才抓到的。）
- **根因**：Windows 上 `os.DirEntry.stat(follow_symlinks=False)` 走的是"不解析重解析点"的取属性通道，这条通道**不回填 `st_dev` 与 `st_ino`**，两者恒为 0；`st_ino == 0` 时所有目录共用同一个键，去重集合塌成 1。对照实测：同一批目录用 `os.stat(e.path, follow_symlinks=False)` 或 `os.lstat(e.path)` 得到**互不相同**的真实 inode（去重集合 6/6）——差别只在"从 `DirEntry` 缓存里取"还是"按路径再 stat 一次"。
- **对策**：① 要用 inode 当键，就现取 `os.stat(e.path, follow_symlinks=False)`（或 `os.lstat(e.path)`），不要用 `e.stat(follow_symlinks=False)`；② 只在 `st_ino != 0` 时把它放进集合（`0` 当作"此平台不提供"，退化为按路径去重）；③ 遍历结束后**必须做一次数量与体积的独立交叉核对**（`du -sh`、`find | wc -l`、或换一条通道重数一遍）——这类塌缩不报错，只有第二个数字能抓它；④ 别把"防循环"和"去重"绑在同一个键上：直接入口用 `os.path.realpath` 的 visited 集 ＋ 深度上限更稳（junction 本身的读法见 `shell-quoting-and-path-forms §12`）。
- **判定**：贴进终端即跑——
  ```python
  import os
  d = r"<装了很多子目录的目录>"
  with os.scandir(d) as it:
      es = [e for e in it if e.is_dir()]
  kd = {(e.stat(follow_symlinks=False).st_dev, e.stat(follow_symlinks=False).st_ino) for e in es}
  ko = {(os.stat(e.path, follow_symlinks=False).st_dev, os.stat(e.path, follow_symlinks=False).st_ino) for e in es}
  print("DirEntry.stat 去重键数 =", len(kd), "/", len(es))
  print("os.stat     去重键数 =", len(ko), "/", len(es))
  print("DirEntry.stat 是否全体 ino==0 =", all(e.stat(follow_symlinks=False).st_ino == 0 for e in es))
  ```
  第一行数字**远小于**第二行（或最后一行打印 `True`）⇒ 命中本条（换 `os.stat` 写法即可）；两行相等且等于子目录数 ⇒ 你的写法没问题。
- **验证于**：Windows 11 家庭中文版 10.0.26200.9457 · Python 3.12.10 · 2026-09-18

## 复用信号

"没报错但数字不对""清洗跑完什么都没变""日期少了一批""对方打开是乱码/多一列""换台机器就不一样""测试全绿但功能是坏的" → 前四个查字节与 dtype，后两个查 `sys.executable` 与版本。
