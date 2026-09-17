---
name: chromium-cdp-on-windows
description: 在 Windows 上用 CDP 自动化操控真实 Chrome 的失效模式与禁令。要操作已登录的网页后台、connect_over_cdp 握手挂起、调试端口起不来、"正在现有会话中打开"、页面越开越卡死、跑到一半 TargetClosedError、浏览器被连带关掉之前读。触发词：9222、remote-debugging-port、user-data-dir、调试 Chrome、target 过多、json/close、末窗口、握手超时、TargetClosedError、Chrome 退出、taskkill、登录页又弹出来。
agent_created: true
---

# Windows 上的 Chrome/CDP 自动化

一句话原则：**你在操控的是用户正在使用的真实浏览器**——它有自己的生命周期规则（末窗口即整体退出）、有自己的安全策略（默认 profile 禁调试端口、不读环境变量代理），而且弄丢一次的代价是用户重新登录。所以下面有几条是禁令，不是建议。

## 1. 默认 profile 上开不了调试端口

- **现象**：带 `--remote-debugging-port=9222` 启动，端口没监听，Chrome 只是把 URL 塞进已经开着的窗口（提示"正在现有的浏览器会话中打开"）。
- **根因**：新版 Chrome（151+ 起）禁止在默认 `User Data` profile 上开调试端口；另外已有实例占用同一 profile 也会合并过去。
- **对策**：**必须显式指定一个非默认的 `--user-data-dir`**，并先确认没有别的 Chrome 实例占着它：
  ```bash
  "C:/Program Files/Google/Chrome/Application/chrome.exe" \
    --remote-debugging-port=9222 --no-first-run --no-default-browser-check \
    --user-data-dir="<项目外专用目录>/chrome_debug_profile"
  ```
  需要视频解码/预览时补 `--use-angle=swiftshader --enable-unsafe-swiftshader`。
- **判定**：`curl -s http://127.0.0.1:9222/json/version` 有 JSON = 端口真的在听。启动后等 9~10 秒再探，太早必然失败。
- **验证于**：Windows 11 家庭中文版 10.0.26200 · Git Bash 5.2.37 · Chrome 153.0.8010.48 · 2026-09-18
- **复测出入（2026-09-18 · Chrome 153.0.8010.48）**：本机隔离实例（专用 profile + 专用端口）实测**启动后 1 秒内** `curl /json/version` 即返回完整 JSON，10 秒后同样正常——"太早必然失败、需等 9~10 秒"在本机不复现；且 `DevTools listening on ws://…` 在启动时直接打印到输出，可据此判就绪。两版并存：以"能拿到 JSON"为唯一就绪判据（原文判定句照旧），固定等待秒数只是保守兜底。

## 2. Chrome 不读环境变量代理

- **现象**：`curl` 同一个 URL 秒回 200，Chrome 里 `net::ERR_TIMED_OUT`。沙箱/企业网机器上尤其常见（出网被强制走代理）。
- **根因**：Chrome 用自己的网络栈与代理配置，**不继承 `HTTP_PROXY` / `HTTPS_PROXY` 环境变量**。
- **对策**：显式传参，并把调试端口本身旁路掉：
  ```
  --proxy-server=http://127.0.0.1:<端口>
  --proxy-bypass-list=127.0.0.1:9222;localhost:9222
  ```
  直连机器不加，无副作用；写成"检测到代理环境变量才加"最稳。
- **判定**：`curl -m 8 -o /dev/null -w "%{http_code}" --proxy http://127.0.0.1:<端口> <url>` 有 200 而浏览器超时 = 就是缺这一条。

## 3. ⛔ 禁令：绝不关掉最后一个 page / 窗口

- **现象**：为"清理干净"而把所有 page 都 `json/close` 掉，结果**整个 Chrome 退出**、9222 消失、用户会话全没，只能重开重登。（这条坑的实际代价：一天内犯两次。）
- **根因**：Chrome 在最后一个窗口关闭时进程整体退出。CDP 的"关页面"操作完全可以触发它。
- **对策（防御性写法，照抄别临场发挥）**：
  1. 启动后**立刻开一个守护页**（导航到固定无害 URL），记下它的 target id，清理逻辑永远跳过它。
  2. 清理重复标签时**保证"关完后剩余 page ≥ 1"**：先算候选集，若 `总 page - 候选数 == 0` 就从候选里剔除至少一个（优先保留用户真实页/守护页）。
  3. 宁可 target 多几个（连接略慢），也不为了"干净"而全关。
- **判定**：任何写 `for t in targets: /json/close/<t>` 的代码都是雷——它等价于"把用户的浏览器关掉"。

## 4. target 堆积会让握手挂起（先数，再动手）

- **现象**：`connect_over_cdp` 挂住无响应、最终超时；或连上了但 `evaluate` / `new_page` 卡住。看起来像网络问题。
- **根因**：脚本每次 `new_page()` 却从不关，几十个 page target 之后 CDP 命令循环本身被拖死。
- **对策 / 判定**（顺序不要反，这一步能省掉一次重启）：
  ```bash
  curl -s http://127.0.0.1:9222/json/list |
    python -c "import sys,json,collections;d=json.load(sys.stdin);print('total',len(d),dict(collections.Counter(t.get('type') for t in d)))"
  ```
  数量离谱就**只精准关脚本自己开的重复 page**（见 §3），再重试 connect。**不要**因为"连不上"就直接杀 Chrome——那是最贵的一步，还会连带丢登录态。
- **验证于**：Windows 11 家庭中文版 10.0.26200 · Git Bash 5.2.37 · Chrome 153.0.8010.48 · python 3.12.10 · 2026-09-18
- **复测确认（2026-09-18 · Chrome 153）**：计数命令实测有效：`total 6 {'background_page': 2, 'page': 1, 'browser_ui': 2, 'service_worker': 1}`。注意新版 Chrome 的 target 类型比 page/iframe 丰富（出现 `background_page`、`browser_ui`、`service_worker`）——统计时按完整 Counter 打出来，别只看 page 数。

## 5. 恢复顺序：按代价从低到高，别跳级

1. `curl /json/version` —— 浏览器进程还活着吗。
2. `curl /json/list` —— target 数是否失控（§4）。
3. 重试 `connect_over_cdp`，**timeout 给到 60000**（30s 会在 ws 已连的情况下仍报 `Timeout 30000ms exceeded`；先探活成功再 connect，重试带 3~4s 退避，实测 3~4 次内自愈）。
4. 仍不行才重启：先干净关（§6）→ 自定义 profile 重启（需要时先继承 Cookie）→ 等端口就绪。
- **验证于**：Windows 11 家庭中文版 10.0.26200 · Git Bash 5.2.37 · Chrome 153.0.8010.48 · 2026-09-18
- **部分复测（2026-09-18）**：第 1、2 步（`/json/version` 探活、`/json/list` 数 target）在隔离实例上实测有效，是重试前最省的两步；第 3 步 `connect_over_cdp` 依赖 CDP 客户端环境，本轮未复测。

## 6. 杀不掉、以及"杀掉"这件事本身

- **现象**：`taskkill //F //IM chrome.exe` 之后 `tasklist` 里 chrome 还在，**命令没有任何报错**。
- **根因**：Git Bash/MSYS 把 `//F` 重写掉了（详见 shell-quoting-and-path-forms §7）。
- **对策**：用**单斜杠** `taskkill /F /IM chrome.exe`；**每次杀完必须 `tasklist | grep -i chrome` 复查**，把输出当证据，不要相信"命令跑完了"。
- **红线**：这只针对脚本自己起的调试 Chrome。用户机器上可能有别的 Chrome 窗口属于他正在做的事——批量关之前先确认不会误杀（关页面/重启等于动用户的账号会话，属于对外可见的动作）。
- **验证于**：Windows 11 家庭中文版 10.0.26200 · Git Bash 5.2.37 · git 2.53.0.windows.2 · cmd 10.0 · 2026-09-18
- **复测出入（2026-09-18 · Git Bash 5.2.37 / git 2.53.0.windows.2，与原文对策方向相反）**：本机实测完整矩阵（全部用不存在的进程名，或本实例 PID，无副作用）：

  | 写法 | 实际结果 |
  |---|---|
  | `taskkill //F //IM <名>`（Git Bash 直调） | **参数正确**：`错误: 没有找到进程 "…"`（解析正常，说明 `//F` 被转成 `/F`） |
  | `taskkill /F /IM <名>`（Git Bash 直调） | **被转换**：`错误: 无效参数/选项 - 'F:/'` —— `/F` 被 MSYS 当路径转成 `F:/` |
  | `cmd /c "echo hello"` | **`/c` 同样被转换**：cmd 进交互模式只打印版本横幅，命令根本没执行 |
  | `cmd //c "echo hello"` / `cmd //c "taskkill /F /IM <名>"` | **正确**：输出 `hello` / `错误: 没有找到进程 "…"` |
  | `MSYS_NO_PATHCONV=1 taskkill /F /IM <名>`（或 `MSYS_NO_PATHCONV=1 cmd /c …`） | **正确**：参数原样传递 |

  真实清理验证：`taskkill //F //PID <本实例 PID>` 退出码 0，随后 `curl /json/version` 立即失联（进程真死）。**结论**：原文"用单斜杠并整体交给 `cmd /c`"在本机环境下两半都不能工作（`/F` 与 `/c` 都会被 MSYS 转换）；Git Bash 直调写 `//F //IM`，需要 cmd 包装写 `cmd //c "taskkill /F /IM …"`，或用 `MSYS_NO_PATHCONV=1` 前缀。两版并存（原文按 cmd.exe 直接调用/旧版 MSYS 理解），同批复测注记见 shell-quoting-and-path-forms §7。

## 7. 登录态继承：复制 profile 的时机与前置条件

- **现象**：把默认 profile 的 `Cookies` 复制到调试 profile，启动后**仍然是登录页**；或者复制"成功"但内容不完整。
- **根因**：Chrome 运行时 Cookie 库被锁，复制得到的是半截文件。
- **对策**：顺序不能换——① 先干净关闭**所有** Chrome 进程（§6，并复查）；② 再复制 `User Data/Default/*`（关键：`Network/Cookies`、`Cookies`、`Preferences`）与 `Local State`（DPAPI 密钥，同一 Windows 用户才能解）；③ 删掉目标 profile 里的 `SingletonLock` / `SingletonCookie` / `SingletonSocket`；④ 启动。
- **⛔ 安全红线**：这类调试 profile 目录里是**真实 Cookie 与登录令牌**，同目录还常留着 `.session.json`。它**永远不能进交付物、同步目录或 git 仓库**。备份/临时 profile 放项目外，并写进 `.gitignore` 与同步排除清单（见 agent-runtime-boundaries §10）。
- **判定**：复制完比对文件字节数（`ls -l`），比"启动看看有没有登录"快，也能发现锁导致的半截复制。

## 8. 登录态是否有效：看响应 body，不看 HTTP 状态码

- **现象**：接口返回 200，脚本以为已登录，实际后续每个写操作都静默失败/被拒。
- **根因**：很多后台在会话失效时仍返回 200，把错误码放在 body 的业务字段里（如 `{"code":"10008"}`）。
- **对策**：登录态探测必须**断言 body 里的业务码/页面标记**，HTTP 状态码只作为传输层信号。
- **判定**：一次"故意未登录"的对照请求，拿到它的真实响应形状，再据此写判据；凭"200 就是好"写的探测在有会话/无会话两种情况下都会返回"正常"。

## 9. 复用上下文，别新建

- **现象**：连上了，但 `new_page()` 出来的标签是空白，或登录态没生效。
- **根因**：用了 `browser.new_context()`——它会创建一个**干净的、未登录的**上下文，与已登录 profile 无关；新标签没 `goto` 时内容区就是空的。
- **对策**：`ctx = b.contexts[0]`（复用已存在的上下文）+ `ctx.new_page()` + 显式 `pg.goto(url)`。
- **判定**：`len(b.contexts)` 为 0 说明连的不是你以为的实例。

## 10. 需要人参与的流程，进程不能由 agent 起

- **现象**：调试 Chrome 由 agent 的工具调用启动，`/json/version` 当场探得到，下一次调用就连不上了——不是崩溃，是被回收。
- **根因**：该调用一结束就回收它派生的全部子进程（详见 agent-runtime-boundaries §1），浏览器进程正是它派生的。
- **对策**：凡中间要扫码/验证码/人工确认的长流程，正解是**让用户在桌面会话里双击启动脚本**，agent 只负责连接；并且脚本按 §5 设计成断连可续。
- **判定**：同一条探测跑两次，中间**不做任何启动动作**——第一次在启动它的那次调用内，第二次在一个新调用里。第一次拿得到 JSON、第二次拿不到（连不上或空输出）＝ 进程被回收，不是端口写错，改走"用户侧启动 + agent 只连"。
- **状态**：复盘条目。判定按流程执行有效，但"哪一次调用回收"的时机未在本机逐字复测，端口一律写 `<端口>`。
- **验证于**：Windows 11 家庭中文版 10.0.26200 · Git Bash 5.2.37 · Chrome 153.0.8010.48 · 2026-09-18
- **复测差异（2026-09-18 · ZCode Bash 工具环境）**：**未复现**回收——`&` 后台启动的隔离调试 Chrome 在两个**独立工具调用**之间持续存活（第二次调用 `curl /json/version` 仍返回完整 JSON），直到手动按 PID 终止。原结论保留（回收行为取决于宿主工具的实现，本条描述的情形可能适用于其他 agent 宿主）；判定方法不变：跨调用探测两次，一次拿得到、一次拿不到即命中。

## 复用信号

"连不上 9222" → §1（profile）或 agent 起的进程被回收（§10）；"curl 通 Chrome 不通" → §2；"越用越卡/握手挂" → §4；"跑到一半 TargetClosedError" → §5 + §10；"复制了 Cookie 还是登录页" → §7；"接口 200 但没登录" → §8。

## 本轮复测范围（2026-09-18）

- **已复测**（§1 / §4 / §5 前两步 / §6 / §10，隔离实例 + 专用 profile 启动，未触碰任何用户会话）：结论见各节注记，其中 §1（就绪等待时间）与 §6（`//F` vs `/F`）各有一处与原文不符或方向相反的出入，已按"保留两版 + 标适用范围"处理。
- **未复测**：§2（需真实代理环境对比）、§3（禁令，不可也不应实测）、§7（涉及真实 Cookie/登录态，红线）、§8（需真实登录场景）、§9（需 CDP 客户端库连接）。未复测 ≠ 不成立，仅表示本轮无人值守条件下未取得新证据。
