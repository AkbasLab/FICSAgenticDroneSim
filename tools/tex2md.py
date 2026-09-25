#!/usr/bin/env python3
"""Convert a line range of the CarlaAir LaTeX manuals to Markdown.

    python tools/tex2md.py <source.tex> <first-line> <last-line> > out.md

Normally driven by build_carlaair_docs.py rather than run directly.

SCOPE -- read this before extending it
--------------------------------------
This is **not** a general LaTeX converter, and should not grow into one. It
handles exactly the constructs the two CarlaAir manuals use:

    \\section / \\subsection / \\subsubsection     -> ##, ###, ####
    lstlisting                                   -> fenced code blocks
    tabular / longtable (booktabs)               -> Markdown tables
    tcolorbox callouts (note/warn/danger/verdict) -> blockquotes
    \\pth, \\textbf, \\emph and friends            -> inline Markdown

Anything else is stripped. That is a deliberate trade: a real LaTeX parser is a
large piece of work, and these two documents are written in a narrow, known
style. If conversion output looks wrong, the fix is usually a new rule here,
not a more clever regex elsewhere.

WHY LINE RANGES AND NOT SECTION NAMES
-------------------------------------
The manuals have no machine-readable structure to select by, and sections are
occasionally split across topics in the output. Ranges keep the selection in
one place (build_carlaair_docs.py) instead of spreading it across two files.

KNOWN LIMITS
------------
* A macro whose argument spans lines is stripped line by line, leaving the
  argument behind -- unwrap_braces() cleans that up afterwards.
* Nested tables and figures are not handled; the manuals contain none.
* Math is passed through with the dollar signs removed, which is enough for the
  handful of "$-8.0$" style values these documents use.
"""

import io
import re
import sys

# tcolorbox environment name -> the blockquote lead-in it becomes. The manual's
# semantic distinction (a warning is not a note) is worth keeping in Markdown,
# which has no callout syntax of its own.
CALLOUT = {
    "note": "> **Note**",
    "warn": "> **Careful**",
    "danger": "> **Important**",
    "verdict": "> **Result**",
}


def inline(text: str) -> str:
    """Convert inline LaTeX macros in one line of text to Markdown.

    ORDER MATTERS. Specific macros are handled first, and the catch-all that
    deletes unknown macros runs last -- otherwise it would eat the very macros
    the earlier rules are waiting for.
    """
    # \pth is the manuals' verbatim-safe path/identifier macro; it and its two
    # cousins all become inline code.
    text = re.sub(r"\\(pth|texttt|lstinline)\{([^{}]*)\}", r"`\2`", text)
    text = re.sub(r"\\textbf\{([^{}]*)\}", r"**\1**", text)
    text = re.sub(r"\\emph\{([^{}]*)\}", r"*\1*", text)
    text = re.sub(r"\\textit\{([^{}]*)\}", r"*\1*", text)
    # \cbtitle is the callout-title macro; the blockquote is added by the caller.
    text = re.sub(r"\\cbtitle\{([^{}]*)\}", r"**\1**", text)

    # Cross-references have no Markdown equivalent worth faking. Labels vanish;
    # a \ref becomes the word "above", which reads correctly in these documents
    # because every reference in them points backwards.
    text = re.sub(r"\\label\{[^{}]*\}", "", text)
    text = re.sub(r"\\hyperref\[[^\]]*\]\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\ref\{[^{}]*\}", "above", text)

    # Typography.
    text = re.sub(r"\\times", "×", text)
    text = re.sub(r"\\ldots", "…", text)
    text = re.sub(r"\\,", " ", text)                    # thin space
    # Escaped specials: in LaTeX these need a backslash, in Markdown they do not.
    text = text.replace("\\%", "%").replace("\\_", "_").replace("\\&", "&")
    text = text.replace("\\#", "#").replace("\\$", "$")
    text = text.replace("``", '"').replace("''", '"')   # TeX quotes
    # An em dash, but not the --- inside a table rule or a code sample.
    text = re.sub(r"(?<!-)---(?!-)", "—", text)
    text = re.sub(r"\$([^$]*)\$", r"\1", text)          # inline math, rare here

    # Catch-all, last: delete any macro not handled above. Its argument, if it
    # had one, survives in braces and is unwrapped later.
    text = re.sub(r"\\[a-zA-Z]+\*?", "", text)
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
    """Pick a syntax-highlighting tag for a code block.

    The manual does not declare a language on its listings, so this guesses
    from content. Wrong guesses cost nothing but colour, hence the cheap
    heuristic rather than anything principled.
    """
    # Python first: its markers are less ambiguous than PowerShell's.
    if re.search(r"^\s*(import |from |client\.|world\.|print\()", body, re.M):
        return "python"
    # $variables, .\script.ps1, Get-Something, foreach, or a bare command.
    if re.search(r"\$\w+|\.\\|Get-|foreach|conda |python |pip ", body):
        return "powershell"
    return "text"


def table(rows: list[str]) -> list[str]:
    """Convert a booktabs tabular body to Markdown table lines.

    Takes the raw source lines BETWEEN \\begin{tabular} and \\end{tabular} and
    returns finished Markdown lines, with a trailing blank line so the table
    does not fuse with the paragraph after it.

    The first surviving row becomes the header, because that is how these
    manuals are written: a header row, \\midrule, then the body.
    """
    cells = []
    for raw in rows:
        # Strip the row terminator, including an optional [6pt] spacing suffix.
        raw = re.sub(r"\\\\(\[\d+pt\])?\s*$", "", raw.strip())
        # Rules are formatting, not content.
        raw = re.sub(r"\\(toprule|midrule|bottomrule|addlinespace|cmidrule\S*)", "", raw)
        if not raw.strip():
            continue

        # Split on unescaped & only: \& is a literal ampersand in a cell.
        row = [inline(c) for c in re.split(r"(?<!\\)&", raw)]

        if not any(cell for cell in row):
            continue                      # blank row, e.g. a longtable spacer
        if cells and row == cells[0]:
            # longtable repeats its header on every page via \endhead. In a
            # 600-row API table that would produce a dozen header rows scattered
            # through the output.
            continue
        cells.append(row)

    if not cells:
        return []

    # \multicolumn rows can be shorter than the rest; pad so Markdown sees a
    # rectangular table, which it requires.
    width = max(len(r) for r in cells)
    cells = [r + [""] * (width - len(r)) for r in cells]

    out = ["| " + " | ".join(cells[0]) + " |",
           "|" + "---|" * width]                      # the header separator
    for row in cells[1:]:
        out.append("| " + " | ".join(row) + " |")
    return out + [""]


def convert(lines: list[str]) -> str:
    """Convert LaTeX source lines to a Markdown document.

    A hand-written line scanner rather than a parser. Each branch recognises
    one construct, consumes however many lines it spans, and appends finished
    Markdown to `out`. The index `i` is advanced explicitly by every branch --
    there is no implicit "next line", because block constructs consume many.

    Recursive for callouts only: their bodies may contain listings and tables.
    """
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i].rstrip("\n")
        stripped = line.strip()

        # Comments and blank lines both collapse to a single blank line, which
        # is what separates paragraphs in Markdown. The guard stops runs of
        # blank lines accumulating.
        if stripped.startswith("%") or not stripped:
            if out and out[-1] != "":
                out.append("")
            i += 1
            continue

        # Headings. The generated file already has an H1 title from the
        # generator's header, so \section starts at H2 and nests from there.
        m = re.match(r"\\(sub)*section\*?\{(.*)\}", stripped)
        if m:
            depth = (stripped.count("subsection") and 1) + (stripped.count("subsubsection") and 1)
            # A heading may carry a trailing \label{...}; drop it.
            title = inline(re.sub(r"\}\s*\\label\{.*", "", m.group(2)))
            out += ["", "#" * (2 + depth) + " " + title.rstrip("}"), ""]
            i += 1
            continue

        # Code listings pass through VERBATIM -- no inline() call. Their braces,
        # backslashes and dollar signs are code, not markup.
        if stripped.startswith("\\begin{lstlisting}"):
            body, i = [], i + 1
            while i < len(lines) and not lines[i].strip().startswith("\\end{lstlisting}"):
                body.append(lines[i].rstrip("\n"))
                i += 1
            text = "\n".join(body)
            out += ["```" + guess_language(text), text, "```", ""]
            i += 1
            continue

        # Tables. tabular and longtable differ only in their end marker here --
        # longtable's pagination directives are dropped by table() and by the
        # skip list further down.
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

        # Callouts become blockquotes. The body is converted RECURSIVELY because
        # these boxes contain listings and tables, then every resulting line is
        # prefixed with "> " to keep it inside the quote.
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

        # Lists: the environment markers carry no content -- Markdown needs only
        # the items themselves, and a blank line to close the list.
        if re.match(r"\\begin\{(itemize|enumerate|description)\}", stripped):
            i += 1
            continue
        if re.match(r"\\end\{(itemize|enumerate|description)\}", stripped):
            out.append("")
            i += 1
            continue
        if stripped.startswith("\\item"):
            # Every item becomes a bullet, including \item[label] in a
            # description list; the label survives inside the text.
            out.append("- " + inline(stripped[5:]))
            i += 1
            continue

        # Pure layout with no Markdown equivalent: centering, page breaks,
        # vertical space, longtable header directives, table rules.
        if re.match(r"\\(begin|end)\{(center|longtable)\}|\\clearpage|\\vfill|\\vspace|"
                    r"\\endfirsthead|\\endhead|\\(top|mid|bottom)rule|\\newpage", stripped):
            i += 1
            continue

        # Anything else is prose.
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
    """Read the requested line range and write Markdown to stdout.

    Deliberately minimal argument handling: the only caller is
    build_carlaair_docs.py, and adding a CLI framework around three positional
    arguments would be more code to maintain than it saves.
    """
    source, first, last = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    with io.open(source, encoding="utf-8") as handle:
        # Line numbers are 1-based, as an editor shows them; slicing is 0-based.
        # `last` is inclusive, which is why there is no -1 on the upper bound.
        lines = handle.readlines()[first - 1:last]
    # Output goes to stdout so the caller decides where it lands; the caller
    # reads it as UTF-8 explicitly.
    sys.stdout.write(convert(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
