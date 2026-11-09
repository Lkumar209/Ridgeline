"""LLM agent layer (M6): tariff-parameter extraction and grounded site explanations.

The model is never trusted on its own. Every output passes a deterministic validator that checks it
against the source text or the numbers it was given, and is rejected otherwise (ADR-014).
"""
