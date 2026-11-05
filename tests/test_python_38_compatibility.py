from typing import get_type_hints

from pyslm_app.services import ModelSession
from pyslm.hatching.hatching import Hatcher
from pyslm.support.support import BlockSupportBase


def test_builtin_generic_annotations_are_runtime_evaluable() -> None:
    targets = (
        ModelSession.compare_orthogonal_orientations,
        Hatcher.clipLines,
        BlockSupportBase.triangulateSections,
    )

    for target in targets:
        get_type_hints(target)
