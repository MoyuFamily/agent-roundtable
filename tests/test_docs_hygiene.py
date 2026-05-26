import re
from pathlib import Path


def test_skill_docs_do_not_contain_direct_core_snippets():
    """Verify that agent-facing SKILL.md docs do not contain code snippets referencing the direct Core API."""
    root_dir = Path(__file__).parent.parent
    docs_to_check = [root_dir / "SKILL.md", root_dir / "src/skills/SKILL.md"]

    for doc_path in docs_to_check:
        assert doc_path.exists(), f"{doc_path} does not exist"
        content = doc_path.read_text(encoding="utf-8")

        # Find all code blocks delimited by triple backticks
        code_blocks = re.findall(r"```\w*\n(.*?)\n```", content, re.DOTALL)
        for block in code_blocks:
            assert "RoundtableCore" not in block, f"Code block in {doc_path.name} contains RoundtableCore reference"
            assert "_get_core" not in block, f"Code block in {doc_path.name} contains _get_core reference"
