"""Process-local Geometry Nodes caches with explicit ownership."""
from __future__ import annotations


_interface_socket_cache = {}
_deform_order_verified = {}


def rna_pointer(value) -> int:
    try:
        return int(value.as_pointer())
    except (AttributeError, ReferenceError, TypeError):
        return 0


def cached_interface_identifiers(cache_key):
    return _interface_socket_cache.get(cache_key)


def cache_interface_identifiers(cache_key, mapping):
    _interface_socket_cache[cache_key] = mapping


def clear_interface_cache():
    _interface_socket_cache.clear()


def verified_deform_order(pointer):
    return _deform_order_verified.get(pointer)


def mark_deform_order(pointer, signature):
    if pointer:
        _deform_order_verified[pointer] = signature


def invalidate_deform_order(value):
    _deform_order_verified.pop(rna_pointer(value), None)


def clear_runtime_state():
    clear_interface_cache()
    _deform_order_verified.clear()
