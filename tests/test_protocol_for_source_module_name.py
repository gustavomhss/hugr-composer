"""Unit test for engine.extraction.infer_protocol.protocol_for_source module_name path.

Covers the generator branch where the inferred `*.protocol.py` needs to
import sibling types defined in the same module — without this the standalone
Protocol file would emit F821 (undefined-name) at the consumer site.

Asserts:
  - Positive: with module_name set, emitted Protocol prepends
    `from <ModuleName> import <Sibling>` line.
  - Negative A: with module_name=None, no import line is emitted.
  - Negative B: the class's OWN name is NOT re-imported.
"""

from __future__ import annotations

import pytest

from engine.extraction.infer_protocol import protocol_for_source

SOURCE_TWO_CLASSES = '''\
class Sibling:
    """A helper type referenced by Handler."""
    pass


class Handler:
    """The class under test."""

    def handle(self, item: Sibling) -> Sibling:
        return item

    def label(self) -> str:
        return "x"
'''


class TestProtocolForSourceModuleName:
    def test_emits_import_line_when_module_name_given(self) -> None:
        protos = protocol_for_source(SOURCE_TWO_CLASSES, module_name="HandlerImpl")
        joined = "\n".join(protos)
        assert "from HandlerImpl import Sibling" in joined, joined

    def test_emits_protocol_class_definition(self) -> None:
        protos = protocol_for_source(SOURCE_TWO_CLASSES, module_name="HandlerImpl")
        joined = "\n".join(protos)
        assert "class HandlerProtocol(Protocol):" in joined, joined
        assert "def handle" in joined, joined
        assert "def label" in joined, joined

    def test_no_import_line_when_module_name_none(self) -> None:
        protos = protocol_for_source(SOURCE_TWO_CLASSES, module_name=None)
        joined = "\n".join(protos)
        assert "from " not in joined, joined

    def test_own_class_name_not_in_import_list(self) -> None:
        protos = protocol_for_source(SOURCE_TWO_CLASSES, module_name="HandlerImpl")
        joined = "\n".join(protos)
        # The class itself is excluded from the import set; only siblings appear.
        assert "import Handler\n" not in joined, joined
        assert "import Sibling" in joined, joined


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
