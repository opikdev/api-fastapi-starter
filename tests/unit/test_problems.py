import re
from pathlib import Path

from app.problems import CATALOG, Slug

ERRORS_DOC = Path(__file__).parents[2] / "docs" / "errors.md"


def test_docs_list_exactly_the_problem_types_in_the_catalog() -> None:
    documented = re.findall(r"^\| `urn:problem:([a-z0-9-]+)` \|", ERRORS_DOC.read_text(), re.M)
    assert len(documented) == len(set(documented)), "docs/errors.md lists a type twice"
    assert set(documented) == {slug.value for slug in CATALOG}
    assert set(CATALOG) == set(Slug)
