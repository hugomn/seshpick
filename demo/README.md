# Demo

The GIF in the main README is recorded against `registry.json`, a made-up list of sessions,
so no real session names or folders ever appear in it.

- `SESHPICK_DEMO_REGISTRY=demo/registry.json seshpick` runs the picker on the fixture and never launches
  anything: picking a session prints the command it would run. Rows carry `ago` (seconds) instead
  of a timestamp so the ages stay fresh whenever the demo is re-recorded.
- `record.sh` records with asciinema and agg if you have them.
- `make_gif.py` draws `seshpick.gif` from plain-text frames of the picker (needs Pillow). This is how
  the current GIF was made: the picker was driven on the fixture, each step captured as text,
  then rendered.
