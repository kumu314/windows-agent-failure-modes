#!/usr/bin/env python3
"""Structural lint + stats for this skill pack.

Usage:
  python scripts/check.py check [--strict]   # strict: warnings also fail
  python scripts/check.py stats
  python scripts/check.py selftest           # prove the filters fire (positive control)

Exit 0 = no error-severity finding. Red-line classes are split ERROR / WARN on
purpose: a lint that cries wolf gets ignored, and a lint that never fires is worse.
"""
import argparse
import os
import re
import sys
from pathlib import Path

# A client only feeds the model a bounded slice of `description`; the widest ceiling
# measured here was ~276 chars, so a longer one loses its tail trigger words. Kept as
# a WARN, not an ERROR: the exact window is client-specific, and a lint that blocks a
# contribution over a number it borrowed from one machine gets ignored everywhere else.
MAX_DESC = 276
SECTION_RE = re.compile(r"^## (\d+)\. (.+)$")
XREF_RE = re.compile(r"([a-z0-9]+(?:-[a-z0-9]+)*)`?\s*§\s*(\d+)")
STAMP_RE = re.compile(r"\*\*验证于\*\*")

# Machine-specific identity tokens (your username, your workspace folder name)
# must NOT be hard-coded here, or the lint itself publishes them. Put one per
# line in scripts/forbidden.local.txt (gitignored); the lint then blocks them.
LOCAL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "forbidden.local.txt")


def _local_tokens():
    if not os.path.exists(LOCAL_FILE):
        return []
    with open(LOCAL_FILE, encoding="utf-8") as fh:
        return [ln.strip() for ln in fh
                if ln.strip() and not ln.lstrip().startswith("#")][:20]


LOCAL_TOKENS = _local_tokens()

# ERROR: would ship a real identity / credential out the door.
REDLINES_HARD = [
    ("real-username", re.compile(r"[\\/]{1,2}(?:Users|home)[\\/]{1,2}(?!<)", re.I)),
    ("credential-shaped", re.compile(r"\b(?:ghp_[A-Za-z0-9]{6,}|sk-[A-Za-z0-9]{16,}|api[_-]?key\s*[:=]\s*\S)")),
    ("personal-home-path", re.compile(r"[A-Za-z]:[\\/](?:Users|home)[\\/]")),
    ("nondefault-proxy-port", re.compile(r"(?:127\.0\.0\.1|localhost):(?!9222\b)\d{4,5}")),
] + [("local-identity-%d" % i, re.compile(re.escape(t), re.I))
     for i, t in enumerate(LOCAL_TOKENS, 1)]
# WARN: keep an eye on it, not automatically a leak.
REDLINES_SOFT = [
    ("bare-drive-path", re.compile(r"(?<!\w)(?!(?:https?|ftp|file|git|ssh):)[A-Za-z]:[\\/](?!<)[\w.\- \u4e00-\u9fff]{2,}")),
    ("known-default-port", re.compile(r"\b(?:7890|7897|1087|8118)\b")),
]
PARTS = (("现象", re.compile(r"\*\*现象")), ("根因", re.compile(r"\*\*根因")),
         ("对策", re.compile(r"\*\*对策")), ("判定", re.compile(r"\*\*判(定|据)")))
# Sections legitimately use other action anchors; any one of these satisfies "可执行判定".
ANCHORS = re.compile(r"判定|判据|止损线|\*\*验证|\*\*红线|\*\*结论")
INLINE_RE = re.compile(r"`[^`\n]{4,}`")
BARE_RE = re.compile(r"§\s*(\d+)")
# Non-entry sections: framing / lists of boundaries. Same pack, different shape.
OVERVIEW_RE = re.compile(r"模型|总览|综述|清单|边界|速查|前提|一览")


def scrub(text):
    return re.sub(r"<[^<>\n]{1,28}>", "", text)


DESC_RE = re.compile(r"^description:[ \t]+(.*)$")


def unq(v):
    """Strip ONE matching pair of surrounding quotes, so a length check measures what
    the loader hands the client rather than the raw line."""
    if len(v) > 1 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def check_description_scalar(path, text):
    """Frontmatter shapes that make a YAML loader reject the whole file — silently
    un-loading the skill in every client — which the regex `key: value` parse below
    cannot see. Deliberately dependency-free so the lint runs on a bare checkout."""
    out = []
    parts = text.split("---\n")
    if len(parts) < 3:
        return out
    for line in parts[1].splitlines():
        m = DESC_RE.match(line)
        if not m:
            continue
        v = m.group(1).strip()
        if not v:
            continue
        q = v[0]
        if q in "\"'":
            if len(v) < 2 or not v.endswith(q):
                out.append(f"{path}: description 以 {q} 开头却没有闭合引号 → YAML PARSE-ERROR")
                continue
            inner = re.sub(r"''" if q == "'" else r'\\"', "", v[1:-1])
            if q in inner:
                out.append(
                    f"{path}: {q}-quoted 的 description 内部还有未转义的 {q}"
                    f" → YAML 在第二个 {q} 处就报错，整颗技能不加载；"
                    f"含 ASCII 双引号的正文应写成单引号标量（内部的 ' 才需写成 ''）")
        elif ": " in v or " #" in v or v.startswith("#"):
            out.append(
                f"{path}: 未加引号的 description 含 `{': ' if ': ' in v else ' #'}`"
                f" → YAML 要么报错要么把后半段当注释丢掉；改用单引号标量")
    return out


def parse(text):
    parts = text.split("---\n")
    if len(parts) < 3:
        return None, ""
    fm, body = parts[1], "\n".join(parts[2:])
    meta = {}
    for line in fm.splitlines():
        m = re.match(r"^(\w+):\s*(.*)$", line)
        if m:
            meta[m.group(1)] = unq(m.group(2).strip())
    return meta, body


def sections(body):
    out, cur = [], None
    for line in body.splitlines():
        m = SECTION_RE.match(line)
        if m:
            cur = {"num": int(m.group(1)), "title": m.group(2), "lines": []}
            out.append(cur)
        elif line.startswith("## "):
            cur = None
        elif cur is not None:
            cur["lines"].append(line)
    return out


def load(skills_dir):
    pack = {}
    for d in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        f = d / "SKILL.md"
        if not f.exists():
            pack[d.name] = {"missing": True}
            continue
        raw = f.read_bytes()
        text = raw.decode("utf-8")
        meta, body = parse(text)
        pack[d.name] = {
            "path": f, "text": text, "meta": meta or {}, "body": body,
            "secs": sections(body), "crlf": raw.count(b"\r\n"), "bom": raw[:3] == b"\xef\xbb\xbf",
        }
    return pack


def scan_redlines(name, path, text):
    hard, soft = [], []
    for i, line in enumerate(scrub(text).splitlines(), 1):
        for label, rx in REDLINES_HARD:
            if rx.search(line):
                hard.append(f"{path}: 红线 {label} @L{i}")
        for label, rx in REDLINES_SOFT:
            if rx.search(line):
                soft.append(f"{path}: {label} @L{i}")
    return hard, soft


def check(pack):
    errs, warns = [], []
    allnums = {s["num"] for e in pack.values() if not e.get("missing") for s in e["secs"]}
    for name, ent in pack.items():
        if ent.get("missing"):
            errs.append(f"{name}: SKILL.md 不存在")
            continue
        p = f"skills/{name}/SKILL.md"
        meta = ent["meta"]
        if meta.get("name") != name:
            errs.append(f"{p}: frontmatter name={meta.get('name')!r} 与目录名不符")
        desc = meta.get("description", "")
        if not desc:
            errs.append(f"{p}: 缺 description")
        elif len(desc) > MAX_DESC:
            warns.append(f"{p}: description {len(desc)} 字 > {MAX_DESC}（超出的尾部触发词客户端根本不给模型看）")
        errs += check_description_scalar(p, ent["text"])
        if meta.get("agent_created") != "true":
            warns.append(f"{p}: 缺 agent_created: true")
        if ent["crlf"]:
            errs.append(f"{p}: 工作树里有 {ent['crlf']} 个 CRLF（应全 LF，见 .gitattributes）")
        if ent["bom"]:
            warns.append(f"{p}: .md 带 BOM")
        nums = [s["num"] for s in ent["secs"]]
        if not nums:
            errs.append(f"{p}: 没有任何 `## N.` 编号节")
        if nums != sorted(nums):
            errs.append(f"{p}: 节号非升序 {nums}")
        dup = {n for n in nums if nums.count(n) > 1}
        if dup:
            errs.append(f"{p}: 节号重复 {sorted(dup)}")
        for s in ent["secs"]:
            seg = "\n".join(s["lines"])
            overview = s["num"] == 0 or bool(OVERVIEW_RE.search(s["title"]))
            code = "```" in seg
            inline = len(INLINE_RE.findall(seg))
            anchored = bool(ANCHORS.search(seg)) or code or inline >= 3
            missing = [nm for nm, rx in PARTS if not rx.search(seg)]
            if len(missing) == 4:
                (warns if (overview or code or inline) else errs).append(f"{p} §{s['num']}: 四段标签全无")
            elif missing and not overview:
                warns.append(f"{p} §{s['num']}: 缺 {'/'.join(missing)}")
            if not anchored:
                errs.append(f"{p} §{s['num']}: 无可执行判定（无判定/判据字样、无代码块、内联命令 <3 条）")
            elif not (ANCHORS.search(seg) or code):
                warns.append(f"{p} §{s['num']}: 判定只藏在内联命令里（{inline} 条），无独立判定行")
            if not STAMP_RE.search(seg):
                warns.append(f"{p} §{s['num']}: 缺环境戳 **验证于**")
            for m in XREF_RE.finditer(seg):
                tgt, tnum = m.group(1), int(m.group(2))
                if tgt == name:
                    continue
                if tgt not in pack:
                    errs.append(f"{p} §{s['num']}: 引用不存在的技能 {tgt}")
                elif tnum not in [x["num"] for x in pack[tgt]["secs"]]:
                    errs.append(f"{p} §{s['num']}: 引用 {tgt} §{tnum} 不存在")
        remainder = XREF_RE.sub(" ", ent["body"])
        for m in BARE_RE.finditer(remainder):
            n = int(m.group(1))
            if n in nums:
                continue
            if n in allnums:
                warns.append(f"{p}: 裸 §{n} 不是本文件节号（本文件 {nums}），请写成 技能名 §N")
            else:
                errs.append(f"{p}: 悬空 §{n}，全包没有任何技能有这一节")
        hard, soft = scan_redlines(name, p, ent["text"])
        errs += hard
        warns += soft
    return errs, warns


DIRTY = """---
name: sample
description: x
---

## 1. 示例

- **现象**：见 `no-such-skill §9`
- **根因**：D:\\SomeTool\\tools\\x.exe 与 C:\\Users\\someone\\x，代理 127.0.0.1:7897，凭据 ghp_ABCDEF123456
- **对策**：读 D:\\work\\keep\\a.txt
- **判定**：跑 `nc -z 127.0.0.1 7897`
"""

CLEAN = """---
name: sample
description: x
agent_created: true
---

## 1. 示例

- **现象**：见 `<某技能> §1`
- **根因**：解释器解析到 <盘符>:\\<项目>\\<工具>\\python.exe
- **对策**：写绝对路径 `<盘符>:\\<项目>`
- **判定**：`git -c http.proxy=http://127.0.0.1:<端口> push`，读回 `--eol` 字段
- **验证于**：OS 10.0 · shell 1 · 工具 1 · 2026-01-01

## 2. 只有止损线的一节

- **现象**：push 不报错
- **根因**：写通道坏了
- **止损线**：重试超过 2 次就停
- **验证于**：OS 10.0 · shell 1 · 工具 1 · 2026-01-01
"""


PROSE = """---
name: sample
description: x
---

## 1. 一段没有命令的话

这件事要小心，通常是因为环境变了，建议观察一下再说。
"""

# Frontmatter shapes, tested both directions: the flagged half must fire (a loader
# would reject or truncate them while a regex parse stays silent), the quiet half
# must NOT (a criterion that cries wolf on valid YAML gets switched off).
FM_CASES = [
    (True,  'description: "触发词 a" 与 b"'),
    (True,  "description: 'don't do this'"),
    (True,  'description: 详见 根因: 是索引坏了'),
    (True,  'description: 尾部说明 # 这半段会被当注释丢掉'),
    (True,  'description: "没闭合的标量'),
    (False, 'description: \'含 "ASCII 双引号" 的单引号标量\''),
    (False, 'description: "干净的双引号标量"'),
    (False, "description: 'it''s escaped'"),
    (False, 'description: 普通标量，中文冒号：不算'),
]


def _pack(text):
    meta, body = parse(text)
    return {"sample": {"path": Path("x"), "text": text, "meta": meta, "body": body,
                       "secs": sections(body), "crlf": 0, "bom": False}}


def selftest():
    dirty = DIRTY
    need = {
        "real-username": "real-username",
        "credential-shaped": "credential-shaped", "nondefault-proxy-port": "nondefault-proxy-port",
        "dangling-xref": "no-such-skill", "bare-drive-path": "bare-drive-path",
    }
    for i, tok in enumerate(LOCAL_TOKENS, 1):
        cls = "local-identity-%d" % i
        need[cls] = cls
        dirty += "\n- 本地清单第 %d 条：D:\\%s\\tools\\x.exe\n" % (i, tok)
    e1, w1 = check(_pack(dirty))
    all1 = " | ".join(e1 + w1)
    missed = [k for k, pat in need.items() if pat not in all1]
    print(f"脏样本：{len(e1)} error / {len(w1)} warning；应命中 {len(need)} 类"
          f"（含 {len(LOCAL_TOKENS)} 条本地清单），未命中 {missed or '无'}")
    for x in e1:
        print("   E:", x)
    e2, w2 = check(_pack(CLEAN))
    print(f"净样本（全占位符 + 带环境戳 + 一节只有止损线）：{len(e2)} error / {len(w2)} warning")
    for x in e2 + w2:
        print("   意外:", x)
    ep, wp = check(_pack(PROSE))
    print(f"纯散文样本（无标签无命令，必须被拒）：{len(ep)} error")
    for x in ep:
        print("   E:", x)
    fm_bad = []
    for should_fire, line in FM_CASES:
        doc = "---\nname: sample\n%s\n---\n\n## 1. x\n\n- **判定**：`ls`\n- **验证于**：a · 1\n" % line
        hits = check_description_scalar("sample", doc)
        if bool(hits) != should_fire:
            fm_bad.append((line, hits[:1]))
    print(f"frontmatter 形状样本：{sum(1 for f, _ in FM_CASES if f)} 条必须响 + "
          f"{sum(1 for f, _ in FM_CASES if not f)} 条不该响，实际错 {len(fm_bad)}")
    for line, hits in fm_bad:
        print("   错:", line, "->", hits)
    if missed or e2 or not ep or fm_bad:
        print("FAIL 过滤器不可信（漏报或误报），先修脚本再信它给的 0")
        return 1
    print("PASS 自检：脏样本全命中、净样本零 error、frontmatter 形状两侧都验过"
          "（占位符 <端口> 不误报，止损线算合法判定锚）")
    return 0


def stats(pack):
    tot_s = tot_l = tot_stamp = 0
    print(f"{'skill':36} {'节':>3} {'行':>5} {'desc':>5} {'有戳':>5}")
    for name, ent in sorted(pack.items()):
        if ent.get("missing"):
            print(f"{name:36} MISSING")
            continue
        lines = len(ent["text"].splitlines())
        stamped = sum(1 for s in ent["secs"] if STAMP_RE.search("\n".join(s["lines"])))
        tot_s += len(ent["secs"])
        tot_l += lines
        tot_stamp += stamped
        print(f"{name:36} {len(ent['secs']):>3} {lines:>5} {len(ent['meta'].get('description', '')):>5} {stamped:>5}")
    print(f"{'TOTAL':36} {tot_s:>3} {tot_l:>5} {'':>5} {tot_stamp:>5}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["check", "stats", "selftest"])
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--root", default=None)
    args = ap.parse_args()
    if args.cmd == "selftest":
        return selftest()
    root = Path(args.root) if args.root else Path(__file__).resolve().parents[1]
    pack = load(root / "skills")
    if args.cmd == "stats":
        return stats(pack)
    errs, warns = check(pack)
    for e in errs:
        print("ERROR", e)
    for w in warns:
        print("WARN ", w)
    print(f"—— {len(errs)} error / {len(warns)} warning · 技能 {len(pack)} 个")
    if errs or (args.strict and warns):
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())
