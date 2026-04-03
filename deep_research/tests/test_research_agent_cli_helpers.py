from pathlib import Path

from research_agent_cli import derive_output_folder


def test_derive_output_folder_uses_final_doc_folder_segment() -> None:
    assert derive_output_folder("./doc/policy") == Path("output") / "policy"
    assert derive_output_folder("./docs/policy") == Path("output") / "policy"
