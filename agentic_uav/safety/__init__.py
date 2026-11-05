"""The runtime safety guardian (AUV-11, Phase 11).

THE BOUNDARY is the agents' (`agents/__init__.py`), enforced by the same test
(`tests/test_sensing.py`): nothing here may import the simulator or the
experiments packages, nor the scenario's ground-truth types. The guardian
knows what its drone knows -- its own readings, the brief, what teammates
said -- and no more, so it can never be "safe" by peeking at the truth.
"""
