#!/usr/bin/env python3
"""Test script for enhanced golden dataset generation with markdown and report."""

import csv
import tempfile
from pathlib import Path


# Test CSV to markdown conversion
def test_csv_to_markdown():
    print("Testing CSV to Markdown conversion...")

    from research_agent.skills.golden_dataset.scripts.golden_dataset_metrics import (
        convert_csv_to_markdown,
        generate_golden_dataset_report,
    )

    # Create a temporary CSV file with metrics
    with tempfile.NamedTemporaryFile(mode='w', suffix='-with-metrics.csv', delete=False) as f:
        writer = csv.writer(f)
        writer.writerow(['ID', 'Coverage Area', 'Question', 'Answer', 'Content',
                         'Similarity', 'Relevance', 'Coherence', 'Groundedness'])
        writer.writerow([
            '1', 'AI Governance', 'What is AI governance?',
            'AI governance refers to the framework...',
            'AI governance is essential for responsible AI development.',
            '4', '85', '4', '5'
        ])
        writer.writerow([
            '2', 'Machine Learning', 'How does ML work?',
            'Machine learning uses algorithms...',
            'ML models learn patterns from data.',
            '3', '70', '3', '4'
        ])
        csv_path = f.name

    try:
        # Convert to markdown
        markdown = convert_csv_to_markdown(csv_path)
        print("\n✓ CSV to Markdown conversion successful!")
        print("\nGenerated Markdown Table:")
        print("=" * 80)
        print(markdown[:500])  # Print first 500 chars
        print("..." if len(markdown) > 500 else "")
        print("=" * 80)

        # Generate final report
        payload = {
            "dataset_name": "AI Governance Dataset",
            "domain": "Artificial Intelligence",
            "items": [
                {"id": "1", "coverage_area": "AI Governance"},
                {"id": "2", "coverage_area": "Machine Learning"}
            ],
            "coverage_areas": ["AI Governance", "Machine Learning"]
        }

        report = generate_golden_dataset_report(
            csv_path=csv_path,
            metrics_csv_path=csv_path,
            markdown_content=markdown,
            payload=payload
        )

        print("\n✓ Final Report generation successful!")
        print("\nReport Preview (first 800 chars):")
        print("=" * 80)
        print(report[:800])
        print("..." if len(report) > 800 else "")
        print("=" * 80)

        return True

    finally:
        # Clean up
        Path(csv_path).unlink()


def test_pipeline_integration():
    print("\n\nTesting Pipeline Integration...")

    from research_agent.skills.golden_dataset.pipeline import evaluate_and_report_golden_dataset

    # Create a temporary directory and CSV
    with tempfile.TemporaryDirectory() as tmpdir:
        output_folder = Path(tmpdir)
        csv_path = output_folder / "test_dataset.csv"

        # Create test CSV
        with open(csv_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['ID', 'Coverage Area', 'Question', 'Answer', 'Content'])
            writer.writerow([
                '1', 'Test Area', 'Test question?',
                'Test answer.', 'Test content.'
            ])

        payload = {
            "dataset_name": "Test Dataset",
            "domain": "Testing",
            "items": [{"id": "1", "coverage_area": "Test Area"}],
            "coverage_areas": ["Test Area"]
        }

        try:
            metrics_csv, markdown_content, final_report = evaluate_and_report_golden_dataset(
                csv_path=csv_path,
                payload=payload,
            )

            print("\n✓ Pipeline integration successful!")
            print(f"\nMetrics CSV: {metrics_csv}")
            print(f"Markdown content length: {len(markdown_content)} chars")
            print(f"Final report length: {len(final_report)} chars")

            # Check files exist
            assert metrics_csv.exists(), "Metrics CSV not created"
            assert (output_folder / "golden_dataset_metrics.md").exists(), "Metrics MD not created by pipeline"
            assert (output_folder / "final_report.md").exists(), "Final report not created by pipeline"

            print("\n✓ All expected files generated!")
            return True

        except Exception as e:
            print(f"\n✗ Pipeline integration failed: {e}")
            import traceback
            traceback.print_exc()
            return False


if __name__ == "__main__":
    print("=" * 80)
    print("Enhanced Golden Dataset Generation - Test Suite")
    print("=" * 80)

    success = True

    try:
        if not test_csv_to_markdown():
            success = False
    except Exception as e:
        print(f"\n✗ CSV to Markdown test failed: {e}")
        import traceback

        traceback.print_exc()
        success = False

    try:
        if not test_pipeline_integration():
            success = False
    except Exception as e:
        print(f"\n✗ Pipeline integration test failed: {e}")
        import traceback

        traceback.print_exc()
        success = False

    print("\n" + "=" * 80)
    if success:
        print("✓ ALL TESTS PASSED!")
    else:
        print("✗ SOME TESTS FAILED")
    print("=" * 80)
