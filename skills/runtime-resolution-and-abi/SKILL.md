---
name: runtime-resolution-and-abi
description: "到底哪个解释器/可执行文件在跑我的代码"——Windows 上多版本运行时并存时的定位与钉死手法。命令存在但退出码奇怪、零输出、装了却找不到、原生模块报 NODE_MODULE_VERSION 不匹配、pip 装了 import 不到、"我本地能跑"之前读。触发词：which python、where node、py -0p、python3 打不开、Command not found、退出码 49、9009、App Execution Alias、WindowsApps、MODULE_NOT_FOUND、NODE_MODULE_VERSION、better-sqlite3、ABI、多版本、PATH 顺序、venv。
agent_created: true
---

# 哪个运行时真的在跑

一句话原则：**"命令能找到"和"命令能跑"是两件事；"能跑"和"跑的是我以为的那个"又是第三件事**。Windows 上三层都经常不一致，判定必须逐层做。

## 1. `python3` 之类的命令"存在"，其实是 0 字节壳

- **现象**（本机实测）：`python3 --version` **零输出、退出码 49**，stdout/stderr 都干净；`which python3` 却有结果。
- **根因**：那是 Microsoft Store 的 App Execution Alias，文件本身 `Length: 0`、`Attributes: Archive, ReparsePoint`。交互式桌面环境下它会去拉起商店页；在自动化/无商店环境里就静默失败，不给任何解释。
- **对策**：把这类"存根"当独立失效类处理——**判据不是"有没有输出"，是退出码 + 文件属性**：
  ```powershell
  Get-Item -LiteralPath "$env:LOCALAPPDATA\Microsoft\WindowsApps\python3.exe" -Force |
    Select-Object Length, Attributes
  ```
  `Length=0` 且带 `ReparsePoint` = 壳，不是解释器。真正的解释器用完整路径调（或在"应用执行别名"里关掉这两个开关）。
- **判定顺序**：`exit code` → `文件属性` → 最后才看输出了什么。

## 2. `py` 启动器会把已卸载的版本继续列给你

- **现象**（本机实测）：`py -0p` 第一行列出 `-V:3.13  C:\<某个早已卸载的目录>\python.exe`，但那个文件**根本不存在**；于是 `py -3` 报
  `Unable to create process using 'C:\...\python.exe -c print(1)': ???????????`（后面那串问号是被控制台代码页毁掉的中文错误消息，见 windows-text-encoding §3），**退出码 101**。
  同机器上 `py -3.12` 正常，退出码 0。
- **根因**：启动器读注册表里的版本登记，卸载不干净的残留项照样列出。
- **对策**：`py -0p` 只当线索；**要跑就用绝对路径**，或明确指到带 `*`（默认）的那一项。脚本、批处理、计划任务里一律写绝对路径解释器，理由见 §4。
- **判定**：`"<列出来的路径>" -c "print(1)"` 的退出码才是结论。注册表项在不在、`py -0p` 说什么，都不算。

## 3. 原生模块的 ABI 是按 Node 版本编译的

- **现象**：同一个 CLI，`node dist/cli.js` 报
  `... NODE_MODULE_VERSION 137. This version of Node.js requires NODE_MODULE_VERSION 127 ... better_sqlite3.node`
  而换另一个 Node 二进制跑同一条命令就正常。
- **根因**：`better-sqlite3` 这类原生插件按编译时的 **模块 ABI**（Node 24 → 137，Node 22 → 127）产出 `.node`，二进制不向后兼容。机器上并存多个 Node（安装版、nvm/volta/fnm 的 shim、IDE 自带）时，`node` 解析到哪个决定成败。
- **对策**：**先用匹配 ABI 的那个二进制跑，别急着重编**。判定：
  ```bash
  node -p "process.versions.modules"      # 当前解释器的 ABI
  where node                              # PATH 里谁在前
  ```
  报错里的两个数字直接告诉你缺哪一边：`137`（模块需要）vs `127`（当前运行时）。只有确认全机器只有一个 Node 且确实需要更新插件时才 `npm rebuild`——那会改共享依赖，影响别的调用方。
- **附带**：同一份 `node_modules` 被两个 Node 版本共用时，**任何一方 rebuild 都会让另一方坏掉**。所以多 Node 环境里"共享 node_modules"本身就是坑，各自装各自的。

## 4. PATH 顺序随 shell 变，同一命令在不同会话解析到不同二进制

- **现象**：Git Bash 里 `node --version` 是 A，PowerShell 里是 B；用户终端能跑，自动化环境报"找不到/版本过低"；计划任务里连命令都找不到。
- **根因**：Machine PATH 与 User PATH 拼接顺序不同、各 shell 的 profile 追加不同目录、Windows 存根目录排在真实安装之后（或之前）。
- **对策**：任何要交付/复用的脚本，**内部写绝对路径**（`D:\...\node.exe`、`C:\...\Python312\python.exe`），别依赖 PATH 解析；`.bat`/`.ps1` 里同理。给非技术用户的东西要"找不到就明确提示改这一行"，否则他们会卡在看不懂的 9009。
- **判定**：
  ```bash
  which -a python python3 node npm        # 列出所有候选与优先级
  ```
  多行输出 = 存在解析歧义，必须钉死。**长任务里把实际用的解释器路径打出来**（`sys.executable` / `process.execPath`），这样日志本身能证明跑的是哪个。

## 5. `MODULE_NOT_FOUND` 常常不是没装，是解析根不对

- **现象**：`require('playwright')` 报 `MODULE_NOT_FOUND`，可项目里明明装了；同一份代码 `cd` 到别的目录跑就好了。
- **根因**：Node 的模块解析从**脚本所在目录**逐级向上找 `node_modules`，不是从当前工作目录；Python 的 `import` 则受 `sys.path[0]`（脚本目录）影响。把脚本放到临时目录、或从别处调用，就换了搜索根。
- **对策**：脚本要引用项目依赖时用**绝对路径 require**（或从项目根用相对路径起脚本），或显式设 `NODE_PATH`；Python 侧 `sys.path.insert(0, str(Path(__file__).parent))` 而不是靠 cwd。
- **判定**：报错信息里会写明它查过哪几个路径——先看那份列表，再决定装不装。缺的是"搜索根"时，重复安装只会掩盖问题，且换个调用方式又复发。

## 6. venv 激活脚本在各 shell 里不一样，未激活不等于安全

- **现象**：`pip install` 装到了全局；或者激活了 venv 但 `python` 仍是系统解释器（PowerShell 执行策略挡了 `Activate.ps1`，命令照样"执行成功"）。
- **对策**：**不依赖激活状态**，直接用 venv 里的解释器绝对路径 `<venv>\Scripts\python.exe -m pip install ...`、`<venv>\Scripts\python.exe script.py`。同理安装依赖永远走 `python -m pip`，让 pip 和 python 必然同前缀。
- **判定**：`python -c "import sys; print(sys.prefix, sys.base_prefix)"` —— 两者不同才是 venv 里；相同就是系统解释器，装了也白装到项目环境。

## 复用信号

"命令存在但什么都不输出""退出码 49/9009/101""我本地能跑""换 shell 就不行""装了却 import 不到""NODE_MODULE_VERSION 对不上" → 一律先测三件事：**真实退出码、`which -a` 的全部候选、以及运行时自己报出的身份**（`sys.executable` / `process.execPath` / `process.versions.modules`）。
