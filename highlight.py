"""Tiny syntax highlighter that outputs Pango markup, plus diff extraction from agent tool calls."""
import os
import re
from html import escape

KW = {
    "rust": "fn let mut pub use mod struct enum impl trait match if else for while loop return self Self crate "
            "super where as in ref move async await const static type unsafe dyn true false Some None Ok Err",
    "py": "def class return if elif else for while in not and or import from as with try except finally raise "
          "lambda yield pass break continue None True False self async await global nonlocal is",
    "js": "function const let var return if else for while of in new class extends import export from default "
          "async await try catch finally throw typeof instanceof this null undefined true false interface type",
    "sh": "if then else elif fi for in do done while case esac function return local export set echo exit",
    "c": "int char void float double long short unsigned signed struct union enum typedef static const return "
         "if else for while do switch case break continue sizeof include define nullptr true false class public "
         "private namespace template auto",
    "lua": "local function end if then else elseif for in do while repeat until return nil true false and or not",
}
LANG = {".rs": "rust", ".py": "py", ".js": "js", ".ts": "js", ".tsx": "js", ".jsx": "js", ".mjs": "js",
        ".sh": "sh", ".bash": "sh", ".zsh": "sh", ".c": "c", ".h": "c", ".cpp": "c", ".hpp": "c", ".cc": "c",
        ".cs": "c", ".java": "c", ".go": "c", ".lua": "lua", ".nix": "sh", ".toml": "sh", ".conf": "sh"}
COMMENT = {"rust": "//", "js": "//", "c": "//", "py": "#", "sh": "#", "lua": "--"}

C_KW, C_STR, C_NUM, C_COM, C_FN, C_TXT = "#c79bff", "#f6c177", "#ff9e64", "#6e6a86", "#7aa2ff", "#e0def4"
TOKEN = re.compile(r'(?P<s>"(?:\\.|[^"\\])*"?|\'(?:\\.|[^\'\\])*\'?)|(?P<n>\b\d[\d_.xXa-fA-F]*\b)|(?P<w>[A-Za-z_]\w*)|(?P<o>.)')


def lang_of(path):
    return LANG.get(os.path.splitext(str(path or ""))[1].lower())


def hl(line, lang):
    kws = set(KW.get(lang, "").split())
    com = COMMENT.get(lang)
    code, comment = line, ""
    if com:
        # split off a trailing comment that isn't inside a string (good enough for a preview)
        i, q = 0, None
        while i < len(line):
            ch = line[i]
            if q:
                if ch == "\\":
                    i += 1
                elif ch == q:
                    q = None
            elif ch in "\"'":
                q = ch
            elif line.startswith(com, i):
                code, comment = line[:i], line[i:]
                break
            i += 1
    out = []
    for m in TOKEN.finditer(code):
        t = escape(m.group())
        if m.group("s"):
            out.append(f"<span foreground='{C_STR}'>{t}</span>")
        elif m.group("n"):
            out.append(f"<span foreground='{C_NUM}'>{t}</span>")
        elif m.group("w"):
            w = m.group()
            nxt = code[m.end():m.end() + 1]
            if w in kws:
                out.append(f"<span foreground='{C_KW}'>{t}</span>")
            elif nxt in "(!":
                out.append(f"<span foreground='{C_FN}'>{t}</span>")
            else:
                out.append(t)
        else:
            out.append(t)
    if comment:
        out.append(f"<span foreground='{C_COM}'><i>{escape(comment)}</i></span>")
    return "".join(out)


def code_from_tool(tool, inp):
    """What an agent tool call changes, for the live code view. None if it isn't code."""
    inp = inp if isinstance(inp, dict) else {}
    fp = inp.get("file_path") or inp.get("notebook_path") or inp.get("path")
    if tool in ("Edit",):
        return {"kind": "edit", "file": fp, "removed": str(inp.get("old_string", "")).splitlines(),
                "added": str(inp.get("new_string", "")).splitlines()}
    if tool == "MultiEdit":
        rem, add = [], []
        for e in inp.get("edits", [])[:4]:
            rem += str(e.get("old_string", "")).splitlines()
            add += str(e.get("new_string", "")).splitlines()
        return {"kind": "edit", "file": fp, "removed": rem, "added": add}
    if tool == "Write":
        return {"kind": "write", "file": fp, "removed": [], "added": str(inp.get("content", "")).splitlines()}
    if tool == "apply_patch":
        patch = str(inp.get("input") or inp.get("patch") or "")
        f, rem, add = None, [], []
        for ln in patch.splitlines():
            if ln.startswith("*** ") and "File:" in ln:
                f = f or ln.split(":", 1)[1].strip()
            elif ln.startswith("-") and not ln.startswith("---"):
                rem.append(ln[1:])
            elif ln.startswith("+") and not ln.startswith("+++"):
                add.append(ln[1:])
        return {"kind": "edit", "file": f, "removed": rem, "added": add}
    cmd = inp.get("command", inp.get("cmd"))
    if cmd is not None and tool not in ("Task", "Agent"):
        if isinstance(cmd, list):
            cmd = " ".join(map(str, cmd))
        return {"kind": "bash", "file": None, "removed": [], "added": str(cmd).splitlines()[:6]}
    return None


def render(code, chars_shown, max_lines=9, width=46):
    """Pango markup for a code change; chars_shown limits the added text (typing effect)."""
    lang = "sh" if code["kind"] == "bash" else lang_of(code.get("file"))
    rows = []

    def cut(s):
        s = s.replace("\t", "    ")
        return s if len(s) <= width else s[: width - 1] + "…"

    if code["kind"] == "bash":
        left = chars_shown
        for ln in code["added"]:
            if left <= 0:
                break
            part = cut(ln)[: max(0, left)]
            left -= len(ln) + 1
            rows.append(f"<span foreground='#9be36b'><b>$</b></span> {hl(part, 'sh')}")
        return "\n".join(rows[:max_lines])
    rem = code["removed"][:3]
    for ln in rem:
        rows.append(f"<span background='#3b1c1c' foreground='#ffb2a8'>- {escape(cut(ln))}</span>")
    left = chars_shown
    budget = max_lines - len(rows)
    for ln in code["added"][:budget]:
        if left <= 0:
            break
        part = cut(ln)[: max(0, left)]
        left -= len(ln) + 1
        rows.append(f"<span background='#16301a'><span foreground='#9be36b'>+</span> {hl(part, lang)}</span>")
    extra = len(code["added"]) - budget
    if extra > 0 and left > 0:
        rows.append(f"<span foreground='{C_COM}'>  … {extra} more lines</span>")
    return "\n".join(rows)
