"""Undo transactions for direct viewport cage edits."""

import bpy


ACTIVE_TRANSACTIONS = set()


def push(message):
    """Push an undo snapshot when the current window supports it."""
    try:
        bpy.ops.ed.undo_push(message=str(message))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False
    return True


def begin(owner, message="Before Cage Control"):
    """Start immediately before the first actual viewport write."""
    key = id(owner)
    if key in ACTIVE_TRANSACTIONS:
        return False
    if not push(message):
        return False
    ACTIVE_TRANSACTIONS.add(key)
    return True


def finish(owner, *, cancel=False, message="Cage Control"):
    """Commit one edit, or discard the active marker after cancellation."""
    key = id(owner)
    if key not in ACTIVE_TRANSACTIONS:
        return False
    if not cancel:
        push(message)
    ACTIVE_TRANSACTIONS.discard(key)
    return True


def clear():
    ACTIVE_TRANSACTIONS.clear()
