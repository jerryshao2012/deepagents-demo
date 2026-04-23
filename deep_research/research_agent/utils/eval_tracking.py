from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_TOOL_FAILURE_PREFIXES = (
    "Invalid JSON payload:",
    "Schema validation failed",
    "Unknown skill",
    "Error invoking tool",
    "ERROR:",
)


def utc_now_iso() -> str:
    """Return current UTC timestamp in ISO8601 format."""
    return datetime.now(timezone.utc).isoformat()


def build_manifest(
        *,
        subject: str,
        skill: str | None,
        doc_folder: str | None,
        no_web: bool,
        model_name: str,
        verify_ssl: str | bool,
) -> dict[str, Any]:
    """Build a canonical test-case manifest for comparability checks."""
    return {
        "subject": (subject or "").strip(),
        "skill": skill,
        "doc_folder": doc_folder,
        "no_web": bool(no_web),
        "model_name": model_name,
        "verify_ssl": str(verify_ssl),
    }


def manifest_hash(manifest: dict[str, Any]) -> str:
    """Return stable SHA256 hash for a manifest."""
    canonical = json.dumps(manifest, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def get_git_sha(cwd: Path | None = None) -> str:
    """Return short git SHA if available, else 'unknown'."""
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            check=True,
        )
        return completed.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _message_role_name_content(message: Any) -> tuple[str, str, str]:
    if isinstance(message, dict):
        role = str(message.get("role", ""))
        name = str(message.get("name", "") or "")
        content = message.get("content", "")
    else:
        role = str(getattr(message, "type", ""))
        name = str(getattr(message, "name", "") or "")
        content = getattr(message, "content", "")

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        content_text = "\n".join(part for part in parts if part)
    else:
        content_text = str(content)

    return role.lower(), name, content_text


def _extract_tool_call_count(message: Any) -> int:
    if isinstance(message, dict):
        tool_calls = message.get("tool_calls")
    else:
        tool_calls = getattr(message, "tool_calls", None)

    if isinstance(tool_calls, list):
        return len(tool_calls)
    return 0


def _extract_usage_metadata(message: Any) -> dict[str, Any]:
    if isinstance(message, dict):
        usage = message.get("usage_metadata") or message.get("response_metadata", {}).get("token_usage")
    else:
        usage = getattr(message, "usage_metadata", None)
        if usage is None:
            response_metadata = getattr(message, "response_metadata", None)
            if isinstance(response_metadata, dict):
                usage = response_metadata.get("token_usage")

    return usage if isinstance(usage, dict) else {}


def collect_run_metrics(result: dict[str, Any], runtime_seconds: float, stream_fallback_used: bool) -> dict[str, Any]:
    """Collect golden-dataset metrics from a run result and runtime context."""
    messages = result.get("messages", [])
    files = result.get("files", {}) if isinstance(result.get("files", {}), dict) else {}

    total_tool_calls = 0
    successful_tool_calls = 0
    failed_tool_calls = 0

    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    saw_token_metadata = False

    for message in messages:
        role, _name, content = _message_role_name_content(message)

        if role in {"ai", "assistant"}:
            total_tool_calls += _extract_tool_call_count(message)

        if role == "tool":
            content_text = content.strip()
            is_failure = not content_text or content_text.startswith(_TOOL_FAILURE_PREFIXES)
            if is_failure:
                failed_tool_calls += 1
            else:
                successful_tool_calls += 1

        usage = _extract_usage_metadata(message)
        if usage:
            saw_token_metadata = True
            prompt_tokens += int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
            completion_tokens += int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
            total_tokens += int(usage.get("total_tokens") or 0)

    if saw_token_metadata and total_tokens == 0:
        total_tokens = prompt_tokens + completion_tokens

    has_metrics_md = "/golden_dataset_metrics.md" in files
    has_final_report = "/final_report.md" in files
    completeness_pass = has_metrics_md and has_final_report

    intervention_required = bool(
        not completeness_pass
        or stream_fallback_used
        or failed_tool_calls > 0
    )

    return {
        "completeness": {
            "pass": completeness_pass,
            "has_golden_dataset_metrics_md": has_metrics_md,
            "has_final_report_md": has_final_report,
        },
        "tool_execution": {
            "total_tool_calls": total_tool_calls,
            "successful_tool_calls": successful_tool_calls,
            "failed_tool_calls": failed_tool_calls,
            "success_rate": (successful_tool_calls / total_tool_calls) if total_tool_calls > 0 else 1.0,
        },
        "failure": {
            "intervention_required": intervention_required,
            "failure_rate": 1.0 if intervention_required else 0.0,
        },
        "token_efficiency": {
            "available": saw_token_metadata,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "tokens_per_successful_task": total_tokens if completeness_pass and saw_token_metadata else None,
        },
        "latency": {
            "runtime_seconds": runtime_seconds,
            "p50_seconds": runtime_seconds,
            "p95_seconds": runtime_seconds,
        },
    }


def make_run_record(
        *,
        manifest: dict[str, Any],
        run_type: str,
        metrics: dict[str, Any],
        runtime_seconds: float,
        model_name: str,
        stream_fallback_used: bool,
        output_file: str,
        git_sha: str,
) -> dict[str, Any]:
    """Build one JSONL entry for an evaluation run."""
    return {
        "timestamp_utc": utc_now_iso(),
        "run_type": run_type,
        "manifest": manifest,
        "manifest_hash": manifest_hash(manifest),
        "model_name": model_name,
        "git_sha": git_sha,
        "runtime_seconds": runtime_seconds,
        "stream_fallback_used": stream_fallback_used,
        "output_file": output_file,
        "metrics": metrics,
    }


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    """Append one JSON object as a line in a JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=True) + "\n")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load a JSONL file into records, skipping empty lines."""
    if not path.exists():
        return []

    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            payload = json.loads(text)
            if isinstance(payload, dict):
                records.append(payload)
    return records


def latest_baseline(records: list[dict[str, Any]], manifest_hash_value: str) -> dict[str, Any] | None:
    """Get most recent baseline record with matching manifest hash."""
    for record in reversed(records):
        if record.get("run_type") == "baseline" and record.get("manifest_hash") == manifest_hash_value:
            return record
    return None


def _metric_verdict(candidate_value: float, baseline_value: float, tolerance: float) -> str:
    if candidate_value > baseline_value * (1 + tolerance):
        return "worse"
    if candidate_value < baseline_value * (1 - tolerance):
        return "better"
    return "same"


def compare_records(
        *,
        baseline: dict[str, Any] | None,
        candidate: dict[str, Any],
        tool_growth_threshold: float = 0.30,
        latency_regression_threshold: float = 0.15,
) -> dict[str, Any]:
    """Compare candidate against baseline for same manifest only."""
    candidate_hash = str(candidate.get("manifest_hash", ""))

    if baseline is None:
        return {
            "comparable": False,
            "overall_verdict": "non-comparable",
            "reason": "no baseline found for manifest",
            "per_metric": {},
        }

    baseline_hash = str(baseline.get("manifest_hash", ""))
    if candidate_hash != baseline_hash:
        return {
            "comparable": False,
            "overall_verdict": "non-comparable",
            "reason": "manifest hash mismatch",
            "per_metric": {},
        }

    base_metrics = baseline.get("metrics", {})
    cand_metrics = candidate.get("metrics", {})

    per_metric: dict[str, str] = {}

    base_complete = bool(base_metrics.get("completeness", {}).get("pass"))
    cand_complete = bool(cand_metrics.get("completeness", {}).get("pass"))
    if cand_complete and not base_complete:
        per_metric["completeness"] = "better"
    elif not cand_complete and base_complete:
        per_metric["completeness"] = "worse"
    else:
        per_metric["completeness"] = "same"

    base_total_tools = int(base_metrics.get("tool_execution", {}).get("total_tool_calls") or 0)
    cand_total_tools = int(cand_metrics.get("tool_execution", {}).get("total_tool_calls") or 0)
    tool_regression = False
    if base_total_tools > 0:
        tool_regression = cand_total_tools > base_total_tools * (1 + tool_growth_threshold)

    if tool_regression and not (cand_complete and not base_complete):
        per_metric["tool_execution"] = "worse"
    elif cand_total_tools < base_total_tools:
        per_metric["tool_execution"] = "better"
    else:
        per_metric["tool_execution"] = "same"

    base_failure = float(base_metrics.get("failure", {}).get("failure_rate") or 0.0)
    cand_failure = float(cand_metrics.get("failure", {}).get("failure_rate") or 0.0)
    if cand_failure > base_failure:
        per_metric["failure"] = "worse"
    elif cand_failure < base_failure:
        per_metric["failure"] = "better"
    else:
        per_metric["failure"] = "same"

    base_tokens_available = bool(base_metrics.get("token_efficiency", {}).get("available"))
    cand_tokens_available = bool(cand_metrics.get("token_efficiency", {}).get("available"))
    if base_tokens_available and cand_tokens_available:
        base_total_tokens = float(base_metrics.get("token_efficiency", {}).get("total_tokens") or 0.0)
        cand_total_tokens = float(cand_metrics.get("token_efficiency", {}).get("total_tokens") or 0.0)
        per_metric["token_efficiency"] = _metric_verdict(cand_total_tokens, base_total_tokens, 0.20)
    else:
        per_metric["token_efficiency"] = "unavailable"

    base_latency = float(base_metrics.get("latency", {}).get("p95_seconds") or 0.0)
    cand_latency = float(cand_metrics.get("latency", {}).get("p95_seconds") or 0.0)
    per_metric["latency"] = _metric_verdict(cand_latency, base_latency, latency_regression_threshold)

    verdict_values = [v for v in per_metric.values() if v in {"better", "same", "worse"}]
    if any(v == "worse" for v in verdict_values):
        overall = "worse"
    elif any(v == "better" for v in verdict_values):
        overall = "better"
    else:
        overall = "same"

    return {
        "comparable": True,
        "overall_verdict": overall,
        "reason": None,
        "per_metric": per_metric,
    }
