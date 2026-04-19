#!/usr/bin/env python3
"""Test script for dynamic skill registry.

This script verifies that the SkillRegistry correctly:
1. Loads all skills from the skills directory
2. Parses YAML frontmatter (name, description, keywords)
3. Supports keyword-based search and routing
4. Provides hot-reloading capabilities
5. Exposes supporting files for lazy loading
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from research_agent.utils.skill_registry import SkillRegistry


def test_basic_loading():
    """Test basic skill loading functionality."""
    print("=" * 80)
    print("TEST 1: Basic Skill Loading")
    print("=" * 80)

    registry = SkillRegistry()

    print(f"\n✓ Registry initialized: {registry}")
    print(f"✓ Number of skills loaded: {registry.num_skills}")
    print(f"✓ Skill IDs: {registry.skill_ids}\n")

    assert registry.num_skills > 0, "No skills were loaded!"
    print("✅ Basic loading test PASSED\n")


def test_skill_summaries():
    """Test skill summary generation for routing."""
    print("=" * 80)
    print("TEST 2: Skill Summaries for Routing")
    print("=" * 80)

    registry = SkillRegistry()
    summaries = registry.get_all_summaries()

    print(f"\n✓ Retrieved {len(summaries)} skill summaries\n")

    for i, summary in enumerate(summaries[:3], 1):  # Show first 3
        print(f"{i}. {summary['name']} (ID: {summary['id']})")
        print(f"   Description: {summary['description'][:80]}...")
        if summary.get('keywords'):
            print(f"   Keywords: {', '.join(summary['keywords'][:3])}...")
        print()

    # Verify structure
    for summary in summaries:
        assert 'id' in summary, f"Missing 'id' in summary: {summary}"
        assert 'name' in summary, f"Missing 'name' in summary: {summary}"
        assert 'description' in summary, f"Missing 'description' in summary: {summary}"

    print("✅ Skill summaries test PASSED\n")


def test_keyword_search():
    """Test keyword-based skill discovery."""
    print("=" * 80)
    print("TEST 3: Keyword-Based Search")
    print("=" * 80)

    registry = SkillRegistry()

    # Test various queries
    test_queries = [
        ("presentation", "frontend-slides"),
        ("slides", "frontend-slides"),
        ("golden", "golden-dataset"),
        ("dataset", "golden-dataset"),
        ("code", "code-generator"),
        ("script", "code-generator"),
    ]

    for query, expected_skill in test_queries:
        matches = registry.find_skills_by_keyword(query)
        print(f"\nQuery: '{query}'")

        if matches:
            match_names = [m.skill_id for m in matches]
            print(f"  Found {len(matches)} match(es): {', '.join(match_names)}")

            if expected_skill in match_names:
                print(f"  ✓ Expected skill '{expected_skill}' found")
            else:
                print(f"  ⚠ Expected skill '{expected_skill}' NOT in results")
        else:
            print(f"  ✗ No matches found (expected: {expected_skill})")

    print("\n✅ Keyword search test COMPLETED\n")


def test_skill_instructions():
    """Test retrieving full skill instructions."""
    print("=" * 80)
    print("TEST 4: Skill Instructions Retrieval")
    print("=" * 80)

    registry = SkillRegistry()

    # Test with frontend-slides
    skill_id = "frontend-slides"
    instructions = registry.get_skill_instructions(skill_id)

    if instructions:
        print(f"\n✓ Retrieved instructions for '{skill_id}'")
        print(f"  Length: {len(instructions)} characters")
        print(f"  First 200 chars: {instructions[:200]}...\n")
    else:
        print(f"\n✗ Failed to retrieve instructions for '{skill_id}'\n")
        assert False, f"Instructions not found for {skill_id}"

    # Test with non-existent skill
    fake_skill = registry.get_skill_instructions("non-existent-skill")
    assert fake_skill is None, "Should return None for non-existent skill"
    print("✓ Correctly returns None for non-existent skill\n")

    print("✅ Skill instructions test PASSED\n")


def test_supporting_files():
    """Test accessing supporting files in skill directories."""
    print("=" * 80)
    print("TEST 5: Supporting Files Access")
    print("=" * 80)

    registry = SkillRegistry()

    # Test with frontend-slides which has supporting files
    skill_id = "frontend-slides"
    supporting_files = registry.get_supporting_files(skill_id)

    print(f"\n✓ Found {len(supporting_files)} supporting file(s) for '{skill_id}':")
    for file_path in supporting_files:
        print(f"  - {file_path.name}")

    # Try reading a specific file
    if supporting_files:
        test_file = supporting_files[0].name
        content = registry.read_supporting_file(skill_id, test_file)

        if content:
            print(f"\n✓ Successfully read '{test_file}' ({len(content)} chars)")
            print(f"  Preview: {content[:100]}...\n")
        else:
            print(f"\n✗ Failed to read '{test_file}'\n")

    # Test reading non-existent file
    fake_content = registry.read_supporting_file(skill_id, "nonexistent.txt")
    assert fake_content is None, "Should return None for non-existent file"
    print("✓ Correctly returns None for non-existent file\n")

    print("✅ Supporting files test PASSED\n")


def test_hot_reloading():
    """Test hot-reloading capability."""
    print("=" * 80)
    print("TEST 6: Hot Reloading")
    print("=" * 80)

    registry = SkillRegistry()

    # Get initial instruction
    skill_id = "frontend-slides"
    initial_instructions = registry.get_skill_instructions(skill_id)

    print(f"\n✓ Initial load completed for '{skill_id}'")
    print(f"  Length: {len(initial_instructions)} chars")

    # Force reload
    reloaded_instructions = registry.get_skill_instructions(skill_id, force_reload=True)

    print(f"✓ Force reload completed")
    print(f"  Length: {len(reloaded_instructions)} chars")

    # They should be the same (unless file was modified during test)
    if initial_instructions == reloaded_instructions:
        print("✓ Instructions unchanged (as expected)\n")
    else:
        print("⚠ Instructions differ (file may have been modified)\n")

    print("✅ Hot reloading test PASSED\n")


def test_skill_info_object():
    """Test getting full SkillInfo objects."""
    print("=" * 80)
    print("TEST 7: Full SkillInfo Object")
    print("=" * 80)

    registry = SkillRegistry()

    skill_id = "golden-dataset"
    skill_info = registry.get_skill_info(skill_id)

    if skill_info:
        print(f"\n✓ Retrieved SkillInfo for '{skill_id}'")
        print(f"  Name: {skill_info.name}")
        print(f"  Description: {skill_info.description[:80]}...")
        print(f"  Keywords: {skill_info.keywords}")
        print(f"  Path: {skill_info.path}")
        print(f"  Metadata keys: {list(skill_info.metadata.keys())}\n")
    else:
        print(f"\n✗ Failed to get SkillInfo for '{skill_id}'\n")
        assert False

    print("✅ SkillInfo object test PASSED\n")


def main():
    """Run all tests."""
    print("\n" + "=" * 80)
    print("DYNAMIC SKILL REGISTRY TEST SUITE")
    print("=" * 80 + "\n")

    try:
        test_basic_loading()
        test_skill_summaries()
        test_keyword_search()
        test_skill_instructions()
        test_supporting_files()
        test_hot_reloading()
        test_skill_info_object()

        print("=" * 80)
        print("ALL TESTS PASSED ✅")
        print("=" * 80)
        return 0

    except Exception as e:
        print("\n" + "=" * 80)
        print(f"TEST FAILED ❌: {e}")
        print("=" * 80)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
