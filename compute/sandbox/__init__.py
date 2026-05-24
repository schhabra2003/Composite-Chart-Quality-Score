"""CCQS V1 — Sandbox (SP500 expansion test environment).

Parallel pipeline that runs the IDENTICAL production compute/* code on an
expanded universe (production + missing SP500 equities, excluding REITs).
Cache, universe, and outputs are isolated from production.
"""
