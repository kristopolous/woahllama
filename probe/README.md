# Probe captures

The raw probe captures (one instruction sent to hosts advertising a given model,
their replies saved) are **not included in this repository**. They contain live
host addresses and are kept private.

The published site ships only the aggregate results in `site/data/probe.json`:
per-model counts of how many hosts answered a simple question correctly versus
replied with fixed filler, and the four rotating version strings. See Chapter 2.
