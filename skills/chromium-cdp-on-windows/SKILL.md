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

- **复测（2026-09-21）：判据换成能证伪的形状后成立——环境变量确实读不到，`--proxy-server` 确实生效**。判据不再看页面内容，改看**服务端自己记的请求行**（HTTP 语义不给解释空间）：本地起一个服务，让 Chrome 去抓它。
  - 只设 `HTTP_PROXY`/`HTTPS_PROXY`（含小写两套）指向一个**没有监听**的端口：服务端照样收到请求，且请求行是 origin 形式 `/probe` ⇒ 直连，环境变量一个字都没被采纳。
  - 同一 URL 加 `--proxy-server=同一个死端口`：服务端**零命中**，Chrome 自己吐出一整页错误 DOM ⇒ 显式参数被采纳。两条一对，"读不读"的差别被证死了。
  - 对照 `curl`：同一份环境（大写或小写变量）下 `curl` 直接 `rc=7`、报错里写明 `over proxy 127.0.0.1` —— 它读。⇒ 分叉来自"两者代理来源不同"，不是"这台机器没有代理这回事"。
- **本机代理来源实测**：注册表 `HKCU\…\Internet Settings` 里 `ProxyEnable=0x1`、`ProxyServer=127.0.0.1:<本机代理端口>`，而 shell 环境变量里**没有任何** proxy 项。⇒ 两套配置各管各的工具，这正是"curl 通、浏览器不通"和反向都会发生的结构性原因。
- **本轮我自己踩到的两个假读数（都写进来，因为它们都会让人下错结论）**：
  1. `--dump-dom=<URL>`（等号形式）**根本不导航**：`rc=0`、输出 10 万余字节的 HTML，看着像抓到了，其实两次不同条件的输出**字节数完全相同**——那是新标签页模板。正确写法是把 URL 作为**独立位置参数**（`--dump-dom` 后面单列）。⇒ 用"换条件后输出字节数是否仍相同"当导航自检。
  2. 拿公网 API 当探针会被限流伪装成代理故障：`https://api.github.com/...` 在这个共享出口 IP 上返回的是"速率超限"正文，页面"没内容"与"代理不通"同形。⇒ 测代理要用**自己能收请求的服务**，别用公网页面的成不成功当判据。
- **验证于**：Windows 11 家庭中文版 10.0.26200.9457（zh-CN）· Chrome 153.0.8010.48（`--headless=new`）· curl 8.18.0 · Python 3.12.10（自建一次性服务）· 2026-09-21
  （env 组 / flag 组 / curl 组为同批读数。**未测到的部分**：本面对"注册表系统代理是否被 Chrome 采纳"未能定论——内网 IP 字面量地址一律走直连旁路，主机名形态本轮未做服务端可见的对照。）

## 3. ⛔ 禁令：绝不关掉最后一个 page / 窗口

- **现象**：为"清理干净"而把所有 page 都 `json/close` 掉，结果**整个 Chrome 退出**、9222 消失、用户会话全没，只能重开重登。（这条坑的实际代价：一天内犯两次。）
- **根因**：Chrome 在最后一个窗口关闭时进程整体退出。CDP 的"关页面"操作完全可以触发它。
- **对策（防御性写法，照抄别临场发挥）**：
  1. 启动后**立刻开一个守护页**（导航到固定无害 URL），记下它的 target id，清理逻辑永远跳过它。
  2. 清理重复标签时**保证"关完后剩余 page ≥ 1"**：先算候选集，若 `总 page - 候选数 == 0` 就从候选里剔除至少一个（优先保留用户真实页/守护页）。
  3. 宁可 target 多几个（连接略慢），也不为了"干净"而全关。
- **判定**：任何写 `for t in targets: /json/close/<t>` 的代码都是雷——它等价于"把用户的浏览器关掉"。

- **复测（2026-09-21，剂量反应 + 模式分叉）**：一律用**自建隔离实例**（独立 `--user-data-dir`，绝不碰用户 profile、绝不连别的会话的端口），看三样同时的读数：命令行含本 profile 标记的 chrome **进程数**、`/json/version` 通不通、page 数。
  - **有头实例**：1 个 page 关掉 → **下一秒进程数 10→0、端口失联**，整台实例自毁。原文这条在有头上完全成立。
  - **有头 2 个 page 只关 1 个** → 进程数 7~13 波动、端口仍活、page 数 1。⇒ 死因不是"关了页面"，是"关到 0"。对照成立。
  - **`--headless=new`**：page 归 0 之后进程数仍 6~12、`/json/version` 10 秒内一直答 `200`。⇒ 无头实例当场**不**自毁。别据此放松：你事先不知道对端起来的是哪一种，而且这条防护针对的是"用户看得见的那台浏览器"。
- **附带（本轮被它咬了两次，判据要改）**：**`Popen` 回来的那个 PID 不是浏览器主进程**。同一台机器上见过两种形态——启动器交接后自己退（`poll()` 返回 21），以及启动器一直活着。所以：
  - "关掉/杀掉"的判据只能是**按 profile 标记复查进程数 == 0**（例：`Get-CimInstance Win32_Process -Filter "Name='chrome.exe'"` 里筛命令行含该目录），不是"命令跑完了"。
  - 优雅关闭走 CDP `Browser.close`（见 §7 复测，1 秒归零），比 `taskkill` 可靠；`taskkill /F /T <启动器 PID>` 实测杀不掉实例。
- **验证于**：Windows 11 家庭中文版 10.0.26200.9457（zh-CN）· Chrome 153.0.8010.48 · 有头与 `--headless=new` 各一组 · 2026-09-21
  （五组试验：有头 1关1 / 有头 2关1 / 无头 1关1 / 无头 2关1 / 无头 2关2，全部按标记数进程；收尾各标记残留 0。）

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

- **复测（2026-09-21，第三次才测成；前两轮的教训一起记）**：用自建隔离 profile，让页面经由一次性本地服务写入一条 Cookie，然后分"运行中 / 归零后"两种状态复制 `Default/Network/Cookies`。
  - **运行中复制不是"半截"，是根本读不出来**：`PermissionError errno=13 拒绝访问`（三次独立复现，同目录常驻 `Cookies` + `Cookies-journal`）。原文"复制成功但内容不完整"在这一版本这一面上没有出现——门槛比想象的更靠前。
  - **干净关闭的正解是 CDP `Browser.close`**：一次 ws 调用（`{"method":"Browser.close"}`）→ 1 秒内该 profile 匹配的进程数归 0。之后单文件复制得 20480 字节，以 `mode=ro` 打开 SQLite **成功**，`select count(*) from cookies` = 1（`host=127.0.0.1, name=probe`），且 `encrypted_value` 非空 ⇒ 值仍是密文，跨 Windows 用户解不出来（与原文 DPAPI 那句一致）。
  - **两轮假结论怎么来的（这一条比结论更有用）**：① 我发了一轮 `Stop-Process` 就认定"关掉了"，复查发现还剩 2 个进程 —— 于是那次"关闭后复制"测的还是运行中状态，结论作废；② 复制件"打不开 SQLite"其实是**我的 URI 写法错**：Windows 反斜杠路径拼 `?mode=ro` 需要转成正斜杠（`as_posix()`），跟文件本身无关。⇒ 归零复查 + 副本可查询，两步都得做，缺一步就会拿运行中状态冒充关闭后。
- **判据补一条**：验证复制件是否可用，用 `select count(*) from cookies` 能不能跑，比 `ls -l` 字节数更硬（本面两次字节数完全相同，可用程度完全不同）。
- **验证于**：Windows 11 家庭中文版 10.0.26200.9457（zh-CN）· Chrome 153.0.8010.48（`--headless=new`，独立 profile）· Python 3.12.10（`shutil.copyfile` + `sqlite3`）· Node v24.18.0（内置 WebSocket 发 CDP）· 2026-09-21
  （**未测到的部分**：真实登录 profile 的整目录继承与 `SingletonLock` 删除步骤本轮未做——那要先干净关掉用户自己的浏览器，不属于可以在探测里顺手做的动作。）

## 8. 登录态是否有效：看响应 body，不看 HTTP 状态码

- **现象**：接口返回 200，脚本以为已登录，实际后续每个写操作都静默失败/被拒。
- **根因**：很多后台在会话失效时仍返回 200，把错误码放在 body 的业务字段里（如 `{"code":"10008"}`）。
- **对策**：登录态探测必须**断言 body 里的业务码/页面标记**，HTTP 状态码只作为传输层信号。
- **判定**：一次"故意未登录"的对照请求，拿到它的真实响应形状，再据此写判据；凭"200 就是好"写的探测在有会话/无会话两种情况下都会返回"正常"。

- **复测（2026-09-21，本地替身把机制坐实）**：起一个故意"说谎"的服务——HTTP 状态码 **200**，body `{"code":"10008","msg":"会话已失效，请重新登录"}`。同一响应两种读数：状态码说"成功"，业务码说"未登录"。⇒ 只断言状态码的探测**必然**在这类响应上盖章通过，这条判据本身可造、可测。
- **适用边界（不外推）**：本轮证明的是"200 与业务码可以相反"这个形状存在且判据该怎么写；**没有**验证任何具体站点当前的响应字段名/错误码含义（那需要一个受控登录态的对端）。落戳只覆盖到"机制 + 判据写法"，接真实服务时仍要按本节原对策先抓一次"故意未登录"的真实响应。
- **验证于**：Windows 11 家庭中文版 10.0.26200.9457（zh-CN）· Python 3.12.10（一次性 `ThreadingHTTPServer`）· 2026-09-21

## 9. 复用上下文，别新建

- **现象**：连上了，但 `new_page()` 出来的标签是空白，或登录态没生效。
- **根因**：用了 `browser.new_context()`——它会创建一个**干净的、未登录的**上下文，与已登录 profile 无关；新标签没 `goto` 时内容区就是空的。
- **对策**：`ctx = b.contexts[0]`（复用已存在的上下文）+ `ctx.new_page()` + 显式 `pg.goto(url)`。
- **判定**：`len(b.contexts)` 为 0 说明连的不是你以为的实例。

- **复测（2026-09-21，不需要 playwright/puppeteer 也能量）**：本机没有任何 CDP 客户端库（`playwright`/`puppeteer`/`puppeteer-core`/`chrome-remote-interface` 全部 MISSING），但 **Node 24 自带 `WebSocket`**，一条 `{"id":1,"method":"Target.createBrowserContext"}` 就能发任意 CDP 命令。用这个把原结论在底层重做一遍：
  - 普通页面（默认上下文）访问本地服务 → 服务端收到 `Cookie: probe=<刚设的值>` ⇒ 复用 profile 登录态。
  - `Target.createBrowserContext` 拿到的 id 里再 `Target.createTarget`（带 `browserContextId`）→ 服务端收到 **`Cookie: None`** ⇒ 新建上下文是干净的，与 profile 无关。Playwright 的 `browser.new_context()` 就是这个对象的封装，故原文成立。
  - 顺带一条实测到的限制：`/json/new?url=…` 这类 HTTP 端点**不接受**上下文参数（想指定上下文必须走 ws）。
- **判据改写（无库环境的等价形式）**：`len(b.contexts)` 只在有 Playwright 时可用；本面等价判据是 `GET /json/version` 里的 `webSocketDebuggerUrl` 指向哪个端口 + `GET /json/list` 里有没有你预期那个 target。连错实例时这两条会直接暴露（端口不是你起的那个 / 列表里没有你的页）。
- **验证于**：Windows 11 家庭中文版 10.0.26200.9457（zh-CN）· Chrome 153.0.8010.48（`--headless=new` + `--remote-allow-origins=*`）· Node v24.18.0（内置 `WebSocket`）· Python 3.12.10（本地服务记 Cookie 头）· 2026-09-21
  （**未测到的部分**：Playwright 层的 `contexts[0]`、`new_page()` 行为未复跑（本机无该库），本节复测在 CDP 层等价物上完成。）

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
