---
name: python-silent-data-errors
description: Windows 上用 Python 读写数据时那些"不报错、结果却是错的"失效模式。跑数据分析/清洗脚本、把结果交给下游读、Excel/CSV 往返、"我明明没报错怎么数字不对"之前读。触发词：pandas、read_csv、read_excel、to_excel、NaT、NaN、dtype object、清洗没生效、空行、多出来一行、\r\r\n、invalid start byte、编码没设 encoding、日期解析不出来、版本升级后结果变了。
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

## 2. `csv.writer` 不加 `newline=''`：每一行后面多一个空行

- **现象**（本机实测）：`open(p,'w')` + `csv.writer` 写出的字节是 `b'a,b\r\r\n1,2\r\r\n'`（多了一个 `\r`）。按文本读回来是 `'a,b\n\n1,2\n\n'`——**每条记录之间都夹一个空行**，`splitlines()` 里出现空条目。行数、报表统计、"是否有数据"的判断全被带偏，且没有任何一方报错。
- **根因**：文本模式把 `\n` 翻译为 `\r\n`，而 csv 自己已经写了 `\r\n` → 双重翻译。
- **对策**：写 `open(p,'w',newline='',encoding='utf-8')`；读 `open(p,newline='',encoding='utf-8-sig')`。
- **判定**：`open(p,'rb').read()` 看真实字节里有没有 `\r\r\n`。有，就是这一条；不要靠"看起来行数对了"。

## 3. `dtype == object` 判断在新版 pandas 上永远为假

- **现象**：清洗脚本跑完，`strip()` / 全角转半角 / 空串归一 一个都没生效，但**没有任何报错**。同一份代码在一台机器有效、另一台无效。
- **根因**：pandas 3.x 起字符串列不再是 `object` dtype，`if df[c].dtype == object:` 恒为 False，整段清洗被跳过；2.x 上它是对的。所以这类 bug 只在"换环境"时暴露，本地怎么测都好。
- **对策**：用类型谓词，别比 dtype 常量：
  ```python
  from pandas.api import types as pdt
  if df[c].dtype == object or pdt.is_object_dtype(df[c]) or pdt.is_string_dtype(df[c]): ...
  ```
- **判定**：`print(repr(df[c].dtype), pd.__version__)` 一行就把环境钉死。**任何"清洗没生效"先跑这行**，别看代码逻辑。

## 4. 混格式日期列：第一种格式胜出，其余静默变 `NaT`

- **现象**：一列里混着 `2026/1/3` 与 `2026-01-15`，`pd.to_datetime(col, errors='coerce')` 后后者全变 `NaT`；不抛错，只是数据少了。
- **根因**：`to_datetime` 一旦推断出格式就锁死它；`errors='coerce'` 又把"解析失败"从异常降格成缺失值。中文日期（`2026年1月16日`）与点分隔（`2026.1.3`）pandas 原生不认。
- **对策**：三步——① 先正则规整成统一形式（`2026年1月16日`/`2026.1.3` → `2026-01-16`/`2026-01-03`）；② `pd.to_datetime(s, errors='coerce', format='mixed')`，外面套 `except (TypeError, ValueError)` 兜住没有 `format='mixed'` 的老版本；③ 对"原始非空但解析后为空"的残余值逐个再试一次。
- **判定（关键，别省）**：算两个数并打印——`原始非空计数` 与 `解析后 notna 计数`。**只要不相等就是有值被 coerce 吃掉了**。顺带注意：coerce 后的 `NaT` 和本来就空的 `NaN` 不可分辨，所以这个差必须在 coerce 那一刻记下，事后无从追溯。

## 5. `to_excel` 写出去的全空行，`read_excel` 读不回来

- **现象**：造了带末尾空行的测试数据，"删除空行"功能怎么写都测不出来；测试全绿。
- **根因**：Excel 读回时末尾全空行会被丢掉——数据在写入环节就没了，与被测逻辑无关。
- **对策**：**测试用空行放中间，不放末尾**（夹在两条有内容的记录之间），或写完立刻断言行数与预期一致。
- **判定**：写完先读回来 `len(df)` 比一下，再生成断言。造数据这一步也要 round-trip，否则测的是"读取器的容忍度"。

## 6. `NaN` / 空串 / 字符串 `"nan"` 是三种不同的东西

- **现象**：`df[col].replace('', None)` 之后仍然"有空值"；`astype(str)` 之后 `NaN` 变成字符串 `"nan"`，参与唯一值统计、分组与文本匹配，且长度非 0、`if x:` 判真。
- **根因**：`astype(str)` 会把缺失值转成**看起来像数据的文本**，一旦做了这一步，缺失信息就永久丢失。
- **对策**：需要文本化时显式指定占位（`df[col].fillna('')` 再 `astype(str)`），并在归一化函数里把 `'nan'/'None'/'NaN'` 一并视为空；下游若按"非空即有效"过滤，就会把这三类字面量当真实值收下。
- **判定**：清洗前后各打印一次 `col.isna().sum()` 与 `(col.astype(str).str.strip()=='' ).sum()`，两个数都记下来；只记一个就无法区分"真没了"和"变成字符串了"。

## 7. 写结果给别人读：把"我怎么写的"一起交付

- **现象**：本地 `df` 一切正常，对方拿到 CSV 后列错位、中文成 `??????`、多出一列空列（索引被写进去了）。
- **根因**：三类默认值共同造成——`to_csv` 未加 `encoding='utf-8-sig'`（Excel 双击打开时把 UTF-8 首列中文名解坏）、未加 `index=False`（多出一列无名索引）、以及 §1/§2 的编码与换行。
- **对策**：交付用 CSV 固定 `df.to_csv(p, index=False, encoding='utf-8-sig', newline='')`；Excel 用户为主才用 `utf-8-sig`（有 BOM 才认得出 UTF-8），纯程序消费用无 BOM UTF-8，并在交付说明里写清是哪一种。
- **判定**：`open(p,'rb').read(3)` 是 `b'\xef\xbb\xbf'` = 带 BOM；再看首行字节而不是看表格软件，表格软件会替你掩盖所有这些问题。

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

## 复用信号

"没报错但数字不对""清洗跑完什么都没变""日期少了一批""对方打开是乱码/多一列""换台机器就不一样""测试全绿但功能是坏的" → 前四个查字节与 dtype，后两个查 `sys.executable` 与版本。
