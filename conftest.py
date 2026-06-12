"""Repo-root conftest.

Its presence puts the repo root on sys.path, so `import guidancegrid` resolves
when running `pytest` from the root without an editable install.
"""
