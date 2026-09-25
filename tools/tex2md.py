#!/usr/bin/env python3
"""Convert a line range of the CarlaAir LaTeX manuals to Markdown.

Written for two specific documents, not as a general LaTeX converter: it
handles the constructs those files actually use — sections, lstlisting blocks,
booktabs tabulars, tcolorbox callouts and the \\pth inline macro.

    python tex2md.py <source.tex> <first-line> <last-line> > out.md
"""

import io
import re
import sys

CALLOUT = {
    "note": "> **Note**",
    "warn": "> **Careful**",
    "danger": "> **Important**",
    "verdict": "> **Result**",
}


def inline(text: str) -> str:
    """Inline macros → Markdown."""
    text = re.sub(r"\\(pth|texttt|lstinline)\{([^{}]*)\}", r"`\2`", text)
    text = re.sub(r"\\textbf\{([^{}]*)\}", r"**\1**", text)
    text = re.sub(r"\\emph\{([^{}]*)\}", r"*\1*", text)
    text = re.sub(r"\\textit\{([^{}]*)\}", r"*\1*", text)
    text = re.sub(r"\\cbtitle\{([^{}]*)\}", r"**\1**", text)
    text = re.sub(r"\\label\{[^{}]*\}", "", text)
    text = re.sub(r"\\hyperref\[[^\]]*\]\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\ref\{[^{}]*\}", "above", text)
    text = re.sub(r"\\times", "×", text)
    text = re.sub(r"\\ldots", "…", text)
    text = re.sub(r"\\,", " ", text)
    text = text.replace("\\%", "%").replace("\\_", "_").replace("\\&", "&")
    text = text.replace("\\#", "#").replace("\\$", "$")
    text = text.replace("``", '"').replace("''", '"')
    text = re.sub(r"(?<!-)---(?!-)", "—", text)
    text = re.sub(r"\$([^$]*)\$", r"\1", text)          # inline math, rare here
    text = re.sub(r"\\[a-zA-Z]+\*?", "", text)          # leftover macros
    return text.strip()


def unwrap_braces(text: str) -> str:
    """Drop braces left behind by a stripped macro.

    Removing \\emph from "\\emph{the simulator freezes}" leaves the argument
    wrapped, which reads as literal braces in the output. Only balanced pairs
    with no nested brace are unwrapped, repeatedly, so nesting resolves inward
    to outward. Runs after the whole document is assembled, because a macro's
    argument can span source lines.
    """
    for _ in range(4):
        text, count = re.subn(r"\{([^{}]*)\}", r"\1", text)
        if not count:
            break
    return text


def guess_language(body: str) -> str:
    if re.search(r"^\s*(import |from |client\.|world\.|print\()", body, re.M):
        return "python"
    if re.search(r"\$\w+|\.\\|Get-|foreach|conda |python |pip ", body):
        return "powershell"
    return "text"


def table(rows: list[str]) -> list[str]:
    """booktabs tabular body → Markdown table."""
    cells = []
    for raw in rows:
        raw = re.sub(r"\\\\(\[\d+pt\])?\s*$", "", raw.strip())
        raw = re.sub(r"\\(toprule|midrule|bottomrule|addlinespace|cmidrule\S*)", "", raw)
        if not raw.strip():
            continue
        row = [inline(c) for c in re.split(r"(?<!\\)&", raw)]
        if not any(cell for cell in row):
            continue                      # blank row, e.g. a longtable spacer
        if cells and row == cells[0]:
            continue                      # longtable repeats its header per page
        cells.append(row)
    if not cells:
        return []
    width = max(len(r) for r in cells)
    cells = [r + [""] * (width - len(r)) for r in cells]
    out = ["| " + " | ".join(cells[0]) + " |",
           "|" + "---|" * width]
    for row in cells[1:]:
        out.append("| " + " | ".join(row) + " |")
    return out + [""]


def convert(lines: list[str]) -> str:
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i].rstrip("\n")
        stripped = line.strip()

        if stripped.startswith("%") or not stripped:
            if out and out[-1] != "":
                out.append("")
            i += 1
            continue

        m = re.match(r"\\(sub)*section\*?\{(.*)\}", stripped)
        if m:
            depth = (stripped.count("subsection") and 1) + (stripped.count("subsubsection") and 1)
            title = inline(re.sub(r"\}\s*\\label\{.*", "", m.group(2)))
            out += ["", "#" * (2 + depth) + " " + title.rstrip("}"), ""]
            i += 1
            continue

        if stripped.startswith("\\begin{lstlisting}"):
            body, i = [], i + 1
            while i < len(lines) and not lines[i].strip().startswith("\\end{lstlisting}"):
                body.append(lines[i].rstrip("\n"))
                i += 1
            text = "\n".join(body)
            out += ["```" + guess_language(text), text, "```", ""]
            i += 1
            continue

        m = re.match(r"\\begin\{(tabular|longtable)\}", stripped)
        if m:
            end = "\\end{%s}" % m.group(1)
            rows, i = [], i + 1
            while i < len(lines) and end not in lines[i]:
                rows.append(lines[i])
                i += 1
            out += table(rows)
            i += 1
            continue

        m = re.match(r"\\begin\{(note|warn|danger|verdict)\}", stripped)
        if m:
            kind = m.group(1)
            body, i = [], i + 1
            while i < len(lines) and not lines[i].strip().startswith("\\end{%s}" % kind):
                body.append(lines[i].rstrip("\n"))
                i += 1
            text = convert(body).strip().split("\n")
            out += [CALLOUT[kind], ">"] + ["> " + t for t in text] + [""]
            i += 1
            continue

        if re.match(r"\\begin\{(itemize|enumerate|description)\}", stripped):
            i += 1
            continue
        if re.match(r"\\end\{(itemize|enumerate|description)\}", stripped):
            out.append("")
            i += 1
            continue
        if stripped.startswith("\\item"):
            out.append("- " + inline(stripped[5:]))
            i += 1
            continue

        if re.match(r"\\(begin|end)\{(center|longtable)\}|\\clearpage|\\vfill|\\vspace|"
                    r"\\endfirsthead|\\endhead|\\(top|mid|bottom)rule|\\newpage", stripped):
            i += 1
            continue

        out.append(inline(line))
        i += 1

    text = "\n".join(out)
    # Unwrap leftover braces in prose only. Code samples use braces for real --
    # PowerShell blocks, Python dicts -- so fenced segments are left untouched.
    segments = text.split("```")
    text = "```".join(
        part if index % 2 else unwrap_braces(part)
        for index, part in enumerate(segments)
    )
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def main() -> int:
    source, first, last = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    with io.open(source, encoding="utf-8") as handle:
        lines = handle.readlines()[first - 1:last]
    sys.stdout.write(convert(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
