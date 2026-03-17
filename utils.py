"""
Shared utilities for Writers Room menu bar app.
"""

from Foundation import NSOperationQueue


def call_on_main(fn) -> None:
    """Schedule fn() to run on the main thread (thread-safe)."""
    NSOperationQueue.mainQueue().addOperationWithBlock_(fn)
