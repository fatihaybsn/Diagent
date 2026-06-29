"""PathFinder-Ship adapter — placeholder for Step 9.

This package will contain the real PathFinder-Ship integration that maps
latency_spike anomalies (instead of cost_spike) to the Diagent core pipeline.

Key design notes for the adapter implementer
---------------------------------------------
*  PathFinder-Ship uses a **local / self-hosted** model (e.g. Ollama).
   Because there is no per-token billing, ``cost_usd`` will typically be
   ``0`` or ``None`` — the ``cost_spike`` detector will therefore not fire.
*  The primary performance signal is **inference latency** (``duration_ms``).
   The adapter should set ``duration_ms`` accurately on each run and rely on
   the ``latency_spike`` detector (env: ``LATENCY_SPIKE_MS``) as the main
   anomaly indicator.
*  Both detectors live in ``core/anomaly_detector.py`` and run on every
   ``POST /runs/{id}/finish`` — no adapter-level opt-in or opt-out is
   needed; the adapter only needs to supply the right data fields.

Until the PathFinder-Ship project is connected, this module intentionally
remains empty.  No production logic should be added here before Step 9.
"""
