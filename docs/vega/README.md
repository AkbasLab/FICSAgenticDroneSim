# The Vega HPC manual

How the study's model, `llama3.3:70b`, is served from an H100 on ERAU's Vega
cluster and reached from the laptop that runs the simulator. It covers getting
in, installing and updating Ollama without root, staging the models, finding
an idle GPU on `gpu01` or `gpu02`, serving the model, the SSH tunnel, running
the experiment, troubleshooting and shutting down.

| | |
|---|---|
| Read | [`vega-carlaair-manual.pdf`](vega-carlaair-manual.pdf) |
| Source | [`vega-carlaair-manual.tex`](vega-carlaair-manual.tex) |

Commands marked **[verified]** were run on Vega and their output observed.
Anything not marked that way is documented but not yet exercised. Paths like
`/scratch/chikhala` are the author's; substitute your own `$USER`.

[`../SETUP.md`](../SETUP.md) §7 has the short version. This is the full one.

## Rebuilding the PDF

The PDF is committed so it can be read without a TeX install. After editing
the source, rebuild it and commit both together:

```powershell
cd docs\vega
```

```powershell
pdflatex -interaction=nonstopmode vega-carlaair-manual.tex
```

Run it twice, so the table of contents and cross-references resolve. The build
files it leaves behind (`.aux`, `.log`, `.out`, `.toc`) are git-ignored.
