# 005 — Python 3.11 reads .pth files in the Windows code page

Date: 2026-11-27 · Jira: LEARNING-233 · PR: #

## Context
Verifying `setup-windows.md` from scratch: a fresh clone in `...\fresh clone thử`, a new venv,
`pip install -e "backend[dev]"`, then the start script.

## What went wrong / surprised me
pip reported success, but `import stuttercut` failed with `No module named 'stuttercut'`. The
editable install had written `_editable_impl_stuttercut.pth` holding the checkout path as UTF-8,
yet the path never appeared in `sys.path`, not even with `PYTHONUTF8=1` / `-X utf8`.

## What I learned
Python 3.11's `site.addpackage` opens `.pth` files with `encoding="locale"`, which on Windows is
the ANSI code page (cp1252) even in UTF-8 mode. "thử" decodes to mojibake, the directory does
not exist, and `site` skips it without a word. Python 3.13 reads `.pth` files as UTF-8 first.
Paths in `PYTHONPATH` reach Python as Unicode, so they are not affected.

Fix: the start scripts put `<repo>/backend` on `PYTHONPATH`; the setup guide asks for an
ASCII-only checkout path (the developer tools run without the script). Video files and the data
folder may still have any name: those paths go through Python strings, not `.pth` files.

## Evidence
```
>>> site.addpackage(site_packages, "_editable_impl_stuttercut.pth", None)   # 3.11.9, Windows
sys.path gained: []          # with -X utf8 too; locale.getencoding() == 'cp1252'
$env:PYTHONPATH = "<repo>\backend"  ->  import stuttercut  ok
```

## Next time
Test setup steps in a folder with a space and a non-ASCII letter, on Windows, before calling a
guide verified.
