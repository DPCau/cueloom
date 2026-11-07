"""Stage 4: quality rules and backfill (self-written core).

Inputs: 20_cues.jsonl + 30_translated.jsonl.
Outputs: 40_qc.jsonl + backfilled cues with flags and auto-fixes.
"""

from __future__ import annotations

import re
import time

from cueloom.config import Config
from cueloom.io.jsonl import read_jsonl, write_jsonl
from cueloom.models import Cue, GlossaryEntry, Job, QcIssue, StageResult
from cueloom.stages.translate import load_glossary

NEGATION_SRC = {"not", "never", "no", "neither", "nor", "none", "没有", "不", "未", "无", "非", "别"}
NEGATION_TGT = {"不", "没", "没有", "未", "无", "非", "别", "not", "never", "no"}


def auto_wrap_lines(text: str, max_chars_per_line: int = 14) -> tuple[str, bool]:
    """Wraps lines that exceed max_chars_per_line without changing text content."""
    lines = text.split("\n")
    if len(lines) > 2:
        return text, False
    if all(len(line) <= max_chars_per_line for line in lines):
        return text, False

    # Try inserting a break at midpoint or punctuation
    joined = text.replace("\n", "")
    if len(joined) <= max_chars_per_line:
        return joined, True

    mid = len(joined) // 2
    # Look for punctuation near midpoint
    punct_pos = -1
    for offset in range(max_chars_per_line // 2):
        for candidate in (mid - offset, mid + offset):
            if 0 < candidate < len(joined) and joined[candidate] in ("，", ",", " ", "、", "；"):
                punct_pos = candidate + 1
                break
        if punct_pos != -1:
            break

    break_at = punct_pos if punct_pos != -1 else mid
    wrapped = joined[:break_at].strip() + "\n" + joined[break_at:].strip()
    return wrapped, True


def check_and_fix(
    cues: list[Cue],
    glossary: list[GlossaryEntry],
    cfg: Config,
) -> tuple[list[Cue], list[QcIssue]]:
    issues: list[QcIssue] = []
    seg_cfg = cfg.raw.get("segment", {}) or {}
    min_cps = float(seg_cfg.get("min_cps", 12))
    max_cps = float(seg_cfg.get("max_cps", 17))
    max_line_chars = int(seg_cfg.get("max_chars_per_line", 14))

    for i, cue in enumerate(cues):
        duration = max(0.001, cue.end - cue.start)

        # 1. time_nonmonotonic
        if cue.end <= cue.start:
            issues.append(
                QcIssue(
                    cue_id=cue.id,
                    code="time_nonmonotonic",
                    severity="error",
                    detail=f"zero or negative duration: {cue.start} -> {cue.end}",
                )
            )

        # 2. time_overlap
        if i > 0 and cue.start < (cues[i - 1].end - 0.001):
            issues.append(
                QcIssue(
                    cue_id=cue.id,
                    code="time_overlap",
                    severity="error",
                    detail=f"overlap with cue {cues[i-1].id}: {cue.start} < {cues[i-1].end}",
                )
            )

        # 3. empty_text / cue_missing
        if not cue.text.strip():
            issues.append(
                QcIssue(
                    cue_id=cue.id,
                    code="empty_text",
                    severity="error",
                    detail="source text is empty",
                )
            )

        if cue.target_text is None or not cue.target_text.strip():
            issues.append(
                QcIssue(
                    cue_id=cue.id,
                    code="cue_missing",
                    severity="error",
                    detail="missing translated text",
                )
            )
            continue

        tgt = cue.target_text.strip()

        # 4. CPS check
        cps = len(tgt.replace("\n", "")) / duration
        if cps > max_cps:
            issues.append(
                QcIssue(
                    cue_id=cue.id,
                    code="cps_high",
                    severity="warn",
                    detail=f"cps {cps:.1f} > {max_cps}",
                )
            )
        elif cps < min_cps:
            issues.append(
                QcIssue(
                    cue_id=cue.id,
                    code="cps_low",
                    severity="warn",
                    detail=f"cps {cps:.1f} < {min_cps}",
                )
            )

        # 5. line_overflow & auto-fix
        lines = tgt.split("\n")
        if any(len(line) > max_line_chars for line in lines) or len(lines) > 2:
            fixed_text, fixed = auto_wrap_lines(tgt, max_line_chars)
            if fixed:
                cue.target_text = fixed_text
                issues.append(
                    QcIssue(
                        cue_id=cue.id,
                        code="line_overflow",
                        severity="warn",
                        detail=f"line wrapped automatically ({tgt!r} -> {fixed_text!r})",
                        auto_fixed=True,
                    )
                )
            else:
                issues.append(
                    QcIssue(
                        cue_id=cue.id,
                        code="line_overflow",
                        severity="warn",
                        detail=f"exceeds line limit: {len(tgt)} chars",
                    )
                )

        # 6. Glossary check
        for entry in glossary:
            src_word = entry.src if entry.case_sensitive else entry.src.lower()
            text_to_check = cue.text if entry.case_sensitive else cue.text.lower()
            if src_word in text_to_check:
                expected_tgt = entry.tgt if not entry.do_not_translate else entry.src
                if expected_tgt not in cue.target_text:
                    issues.append(
                        QcIssue(
                            cue_id=cue.id,
                            code="term_miss",
                            severity="error",
                            detail=f"term {entry.src!r} not translated as {expected_tgt!r}",
                        )
                    )

        # 7. Digit check
        src_digits = re.findall(r"\d+", cue.text)
        tgt_digits = re.findall(r"\d+", cue.target_text)
        if set(src_digits) != set(tgt_digits) and src_digits:
            issues.append(
                QcIssue(
                    cue_id=cue.id,
                    code="digit_mismatch",
                    severity="error",
                    detail=f"digits mismatch: source {src_digits} vs target {tgt_digits}",
                )
            )

        # 8. Negation risk
        src_words = set(re.findall(r"\w+", cue.text.lower()))
        if any(neg in src_words for neg in NEGATION_SRC):
            if not any(neg in cue.target_text for neg in NEGATION_TGT):
                issues.append(
                    QcIssue(
                        cue_id=cue.id,
                        code="negation_risk",
                        severity="warn",
                        detail="source contains negation but target does not",
                    )
                )

        # 9. Length ratio
        if len(cue.text) > 0:
            ratio = len(cue.target_text) / len(cue.text)
            if ratio < 0.2 or ratio > 3.5:
                issues.append(
                    QcIssue(
                        cue_id=cue.id,
                        code="length_ratio",
                        severity="warn",
                        detail=f"length ratio {ratio:.2f} outside [0.2, 3.5]",
                    )
                )

    # Attach issue codes to cue.flags
    issue_map: dict[int, list[str]] = {}
    for issue in issues:
        issue_map.setdefault(issue.cue_id, []).append(issue.code)
    for cue in cues:
        cue.flags = list(set(cue.flags + issue_map.get(cue.id, [])))

    return cues, issues


def run(job: Job, cfg: Config) -> StageResult:
    start_t = time.monotonic()
    work_job = cfg.work_dir / job.job_id
    cues_file = work_job / "20_cues.jsonl"
    if not cues_file.exists():
        raise FileNotFoundError(f"missing 20_cues.jsonl for job {job.job_id}")

    cues = read_jsonl(cues_file, model=Cue)
    _, glossary = load_glossary(cfg.root)

    cues, issues = check_and_fix(cues, glossary, cfg)
    write_jsonl(work_job / "40_qc.jsonl", issues)
    # Save backfilled & auto-fixed cues
    write_jsonl(cues_file, cues)

    warnings = [f"cue {iss.cue_id} [{iss.code}]: {iss.detail}" for iss in issues if iss.severity == "warn"]
    has_errors = any(iss.severity == "error" for iss in issues)

    return StageResult(
        stage="qc",
        ok=not has_errors,
        count=len(issues),
        duration_sec=round(time.monotonic() - start_t, 2),
        warnings=warnings,
    )
