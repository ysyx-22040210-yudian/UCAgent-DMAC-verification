"""Built-in EDA adapters and their process-wide registry."""

from .base import ToolchainAdapter, get_adapter, list_adapters, register_adapter
from .formal_mc import FormalMcAdapter
from .picker import PickerAdapter
from .pytest import PytestAdapter
from .urg import UrgAdapter
from .vc_formal import VcFormalAdapter
from .sby import SbyAdapter
from .vcs import VcsAdapter
from .verdi import VerdiArtifactAdapter


for _adapter in (
    PickerAdapter(),
    PytestAdapter(),
    VcsAdapter(),
    UrgAdapter(),
    VcFormalAdapter(),
    SbyAdapter(),
    FormalMcAdapter(),
    VerdiArtifactAdapter(),
):
    register_adapter(_adapter)


__all__ = [
    "FormalMcAdapter",
    "PickerAdapter",
    "PytestAdapter",
    "ToolchainAdapter",
    "UrgAdapter",
    "VcFormalAdapter",
    "SbyAdapter",
    "VcsAdapter",
    "VerdiArtifactAdapter",
    "get_adapter",
    "list_adapters",
    "register_adapter",
]
