"""Root-package import contract without the optional sparse extra.

``bitongue.filter`` must stay importable when the sparse extra's
dependencies (fastembed, jieba, qdrant-client) are absent; the sparse
subpackage is only touched when imported directly.
"""

import subprocess
import sys
from textwrap import dedent

BLOCKED = ("fastembed", "jieba", "qdrant_client")

SCRIPT = dedent(
    f"""
    import sys


    class Blocker:
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] in {BLOCKED!r}:
                raise ModuleNotFoundError(f"No module named {{name!r}}", name=name)
            return None


    sys.meta_path.insert(0, Blocker())

    from bitongue.filter import BaseFilter, KeywordsFilter, Normalizer

    assert BaseFilter is not None
    assert KeywordsFilter is not None
    assert Normalizer is not None

    try:
        from bitongue.filter.sparse import SparseTextualFilter  # noqa: F401
    except ModuleNotFoundError as exc:
        assert exc.name in {BLOCKED!r}
    else:
        raise AssertionError("sparse import should fail without the extra")
    """
)


class TestRootImportsWithoutSparseExtra:
    """``bitongue.filter`` imports cleanly without sparse dependencies."""

    def test_filter_imports_without_sparse_dependencies(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", SCRIPT],
            capture_output=True,
            text=True,
            check=False,
        )

        assert proc.returncode == 0, proc.stderr
