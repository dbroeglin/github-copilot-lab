"""A tiny calculator with a deliberate bug for Copilot to fix."""


def add(a, b):
    return a + b


def subtract(a, b):
    return a - b


def multiply(a, b):
    # BUG: this should multiply, not add.
    return a + b
