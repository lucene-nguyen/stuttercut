# Test media

Synthetic clips are generated at test time by FFmpeg (`lavfi` sources such as `testsrc` and
`sine`) in a `conftest.py` fixture, into a temporary folder. They are never committed.

`*.mp4` and `*.wav` stay ignored by `.gitignore`. Real voices belong to the private golden set
(see `eval/`), never here.
