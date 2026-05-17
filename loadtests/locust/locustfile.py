from __future__ import annotations

import os
from importlib import import_module

from loadtests.locust.users.auth_burst import AuthBurstUser
from loadtests.locust.users.mixed_crud import MixedCrudUser
from loadtests.locust.users.read_heavy import ReadHeavyUser


_SHAPE_IMPORTS = {
    "soak": ("loadtests.locust.shapes.soak", "SoakShape"),
    "spike": ("loadtests.locust.shapes.spike", "SpikeShape"),
    "step": ("loadtests.locust.shapes.step_load", "StepLoadShape"),
}
_shape_exports: list[str] = []
_selected_shape = os.environ.get("EDILCLOUD_LOADTEST_SHAPE", "").strip().lower()

if _selected_shape:
    try:
        module_path, class_name = _SHAPE_IMPORTS[_selected_shape]
    except KeyError as exc:
        raise RuntimeError(f"Unsupported EDILCLOUD_LOADTEST_SHAPE={_selected_shape}") from exc
    globals()[class_name] = getattr(import_module(module_path), class_name)
    _shape_exports.append(class_name)


__all__ = [
    "AuthBurstUser",
    "MixedCrudUser",
    "ReadHeavyUser",
    *_shape_exports,
]
