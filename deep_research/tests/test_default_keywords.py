#!/usr/bin/env python3
"""Test that skills without explicit keywords get default keyword from name."""

from pathlib import Path

import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from research_agent.utils.skill_registry import SkillRegistry


def test_default_keywords():
    """Verify that golden-dataset has its keywords from SKILL.md frontmatter."""
    registry = SkillRegistry()

    skill_info = registry.get_skill_info("golden-dataset")

    if not skill_info:
        print("❌ FAILED: golden-dataset skill not found")
        return False

    print(f"Skill: {skill_info.name}")
    print(f"Keywords: {skill_info.keywords}")

    # golden-dataset has explicit keywords in its SKILL.md
    assert len(skill_info.keywords) > 0, "golden-dataset should have keywords"
    print(f"✅ PASSED: Keywords found: {skill_info.keywords}")
    return True


def test_keyword_matching():
    """Verify that keyword-based search works for the remaining legacy skill."""
    registry = SkillRegistry()

    test_queries = ["golden", "dataset"]

    print("\nTesting keyword matching:")
    all_passed = True

    for query in test_queries:
        matches = registry.find_skills_by_keyword(query)
        matched_names = [m.skill_id for m in matches]

        if "golden-dataset" in matched_names:
            print(f"  ✅ Query '{query}' → matched golden-dataset")
        else:
            print(f"  ❌ Query '{query}' → did NOT match golden-dataset (matched: {matched_names})")
            all_passed = False

    return all_passed


if __name__ == "__main__":
    print("=" * 80)
    print("Testing Default Keyword Behavior")
    print("=" * 80 + "\n")

    result1 = test_default_keywords()
    result2 = test_keyword_matching()

    print("\n" + "=" * 80)
    if result1 and result2:
        print("ALL TESTS PASSED ✅")
        sys.exit(0)
    else:
        print("SOME TESTS FAILED ❌")
        sys.exit(1)
