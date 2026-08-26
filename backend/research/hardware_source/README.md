Raw source data for the hardware database, used only by
`scripts/generate_hardware_rankings.py` and
`scripts/normalize_gpu_database.py` to (re)build
`data/hardware/normalized/*.json` and `data/hardware/rankings/*.json`.

Not read by the running app — moved out of `data/hardware/` so it
doesn't ship with the Render deploy. Point the generation scripts at
`research/hardware_source/source/` when you need to regenerate.
