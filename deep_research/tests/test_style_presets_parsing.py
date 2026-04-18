#!/usr/bin/env python3
"""Test dynamic STYLE_PRESETS.md parsing."""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from research_agent.tools import _load_frontend_slides_style_presets


def test_dynamic_preset_loading():
    """Test that style presets are loaded dynamically from STYLE_PRESETS.md."""
    print("=" * 80)
    print("Testing Dynamic Style Preset Loading")
    print("=" * 80 + "\n")

    presets = _load_frontend_slides_style_presets()

    print(f"✓ Loaded {len(presets)} style presets\n")

    # Check that we have the expected presets from STYLE_PRESETS.md
    expected_presets = [
        "Bold Signal",
        "Electric Studio",
        "Creative Voltage",
        "Dark Botanical",
        "Notebook Tabs",
        "Pastel Geometry",
        "Split Pastel",
        "Vintage Editorial",
        "Neon Cyber",
        "Terminal Green",
        "Swiss Modern",
        "Paper & Ink"
    ]

    all_found = True
    for preset_name in expected_presets:
        if preset_name in presets:
            print(f"✅ Found: {preset_name}")

            # Verify structure
            preset = presets[preset_name]
            required_keys = ['font_href', 'font_display', 'font_body',
                             'bg_primary', 'text_primary', 'accent']

            missing_keys = [k for k in required_keys if k not in preset]
            if missing_keys:
                print(f"   ⚠️  Missing keys: {missing_keys}")
            else:
                print(f"   ✓ Has all required configuration keys")
        else:
            print(f"❌ Missing: {preset_name}")
            all_found = False

    print("\n" + "=" * 80)
    if all_found and len(presets) >= len(expected_presets):
        print("✅ ALL TESTS PASSED - Dynamic loading works!")
        print(f"   Total presets loaded: {len(presets)}")
        return 0
    else:
        print("⚠️  Some presets may be missing or incomplete")
        print(f"   Expected at least {len(expected_presets)}, got {len(presets)}")
        return 1


if __name__ == "__main__":
    sys.exit(test_dynamic_preset_loading())
