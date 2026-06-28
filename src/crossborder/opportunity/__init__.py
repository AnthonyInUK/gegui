"""Opportunity discovery engine.

Bottom-up product selection: instead of a human handing the system a keyword,
this package fuses multiple demand signals (Google Trends momentum, Amazon
best-seller rank, review pain density) into a ranked list of niche
opportunities. Each signal source is a pluggable DemandSignalProvider so the
ranking engine stays the same whether a signal is live, cached, or a snapshot.
"""
