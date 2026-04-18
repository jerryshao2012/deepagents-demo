#!/usr/bin/env python3
"""Test that skills without keywords get default keyword from name."""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from research_agent.skill_registry import SkillRegistry


def test_default_keywords():
    """Verify that frontend-slides gets 'frontend slides' as default keyword."""
    registry = SkillRegistry()

    # Get frontend-slides skill info
    skill_info = registry.get_skill_info("frontend-slides")

    if not skill_info:
        print("❌ FAILED: frontend-slides skill not found")
        return False

    print(f"Skill: {skill_info.name}")
    print(f"Keywords: {skill_info.keywords}")

    # Check that it has the default keyword
    expected_keyword = "frontend slides"
    if expected_keyword in skill_info.keywords:
        print(f"✅ PASSED: Default keyword '{expected_keyword}' found")
        return True
    else:
        print(f"❌ FAILED: Expected keyword '{expected_keyword}' not in {skill_info.keywords}")
        return False


def test_keyword_matching():
    """Verify that searching for 'frontend' or 'slides' matches the skill."""
    registry = SkillRegistry()

    # Test various queries
    test_queries = ["frontend", "slides", "presentation", "frontend slides"]

    print("\nTesting keyword matching:")
    all_passed = True

    for query in test_queries:
        matches = registry.find_skills_by_keyword(query)
        matched_names = [m.skill_id for m in matches]

        if "frontend-slides" in matched_names:
            print(f"  ✅ Query '{query}' → matched frontend-slides")
        else:
            print(f"  ❌ Query '{query}' → did NOT match frontend-slides (matched: {matched_names})")
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
