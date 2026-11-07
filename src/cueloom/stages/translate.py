"""Stage 3: cue-level translation orchestration (self-written core).

Inputs: 20_cues.jsonl + glossary.
Outputs: 30_translated.jsonl with backfilled Cue.target_text.
Hard invariants: Timecodes (start/end) are NEVER sent to LLM and NEVER modified.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import yaml

from cueloom.config import Config
from cueloom.io.jsonl import read_jsonl, write_jsonl
from cueloom.llm.cache import cache_key
from cueloom.llm.client import LlmClient, MockLlmClient, OpenAiCompatibleClient
from cueloom.llm.schema import RESPONSE_SCHEMA
from cueloom.models import Cue, GlossaryEntry, Job, StageResult


def load_glossary(root: Path) -> tuple[str, list[GlossaryEntry]]:
    for name in ("configs/glossary.yaml", "configs/glossary.example.yaml"):
        file = root / name
        if file.exists():
            try:
                data = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
                entries_raw = data.get("entries", [])
                entries = [GlossaryEntry(**e) for e in entries_raw]
                version = str(data.get("version", "v1"))
                return version, entries
            except Exception:
                continue
    return "v1", []


def load_system_prompt(root: Path) -> tuple[str, str]:
    file = root / "configs" / "prompts" / "translate.system.md"
    if file.exists():
        content = file.read_text(encoding="utf-8").strip()
        version = "v1"
        for line in content.splitlines():
            if line.startswith("版本："):
                version = line.replace("版本：", "").strip()
        return version, content
    default_prompt = (
        'You are a professional subtitle translator. Output JSON only: {"items":[{"id":0,"text":"..."}]}. '
        "Preserve terminology and numbers. Never output timecodes."
    )
    return "v1", default_prompt


def build_batches(cues: list[Cue], cfg: Config) -> list[list[Cue]]:
    batch_max_items = cfg.llm.batch_max_items
    batch_max_tokens = cfg.llm.batch_max_tokens

    batches: list[list[Cue]] = []
    current_batch: list[Cue] = []
    current_tokens = 0

    for cue in cues:
        # Simple token estimation: chars / 2
        est_tokens = max(1, len(cue.text) // 2)
        if current_batch and (
            len(current_batch) >= batch_max_items
            or (current_tokens + est_tokens) > batch_max_tokens
        ):
            batches.append(current_batch)
            current_batch = [cue]
            current_tokens = est_tokens
        else:
            current_batch.append(cue)
            current_tokens += est_tokens

    if current_batch:
        batches.append(current_batch)
    return batches


def _get_client(cfg: Config) -> LlmClient:
    if cfg.llm.configured:
        return OpenAiCompatibleClient(cfg.llm)
    return MockLlmClient()


def _translate_batch_with_retry(
    client: LlmClient,
    system: str,
    payload: dict,
    batch_cues: list[Cue],
    retries: int = 3,
) -> dict[int, str]:
    """Translates a batch; falls back to single-cue translation if batch fails."""
    expected_ids = {c.id for c in batch_cues}
    last_err: Exception | None = None

    for attempt in range(retries):
        try:
            data = client.complete_json(system, payload, RESPONSE_SCHEMA)
            items = data.get("items", [])
            mapping = {it["id"]: it["text"].strip() for it in items if "id" in it and "text" in it}
            if set(mapping.keys()) == expected_ids:
                return mapping
            raise ValueError(f"id mismatch: expected {expected_ids}, got {set(mapping.keys())}")
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(0.1 * (2**attempt))

    # Degradation: single-cue retries
    fallback_mapping: dict[int, str] = {}
    for cue in batch_cues:
        single_payload = dict(payload)
        single_payload["items"] = [{"id": cue.id, "text": cue.text}]
        translated_text = None
        for _ in range(retries):
            try:
                single_data = client.complete_json(system, single_payload, RESPONSE_SCHEMA)
                for it in single_data.get("items", []):
                    if it.get("id") == cue.id and it.get("text"):
                        translated_text = it["text"].strip()
                        break
                if translated_text:
                    break
            except Exception:
                time.sleep(0.1)

        fallback_mapping[cue.id] = translated_text or f"[Translation Error: {type(last_err).__name__}]"

    return fallback_mapping


def translate_cues(
    cues: list[Cue],
    glossary: list[GlossaryEntry],
    cfg: Config,
    job: Job,
) -> tuple[list[Cue], list[dict]]:
    """Translates cues with per-cue caching and backfills Cue.target_text."""
    if not cues:
        return [], []

    # Record original timecodes to verify invariance
    orig_timecodes = {c.id: (c.start, c.end) for c in cues}

    prompt_version, system_prompt = load_system_prompt(cfg.root)
    job.prompt_version = prompt_version
    glossary_version, loaded_glossary = load_glossary(cfg.root)
    if not glossary:
        glossary = loaded_glossary
    job.glossary_version = glossary_version

    cache_dir = cfg.work_dir / job.job_id / "llm_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    client = _get_client(cfg)

    translated_records: list[dict] = []
    uncached_cues: list[Cue] = []
    cue_map: dict[int, Cue] = {c.id: c for c in cues}

    # Step 1: Check cache
    for cue in cues:
        key = cache_key(
            model=cfg.llm.model or "default",
            prompt_version=prompt_version,
            glossary_version=glossary_version,
            source_lang=job.source_lang or "auto",
            target_lang=job.target_lang,
            text=cue.text,
        )
        cache_file = cache_dir / f"{key}.json"
        if cfg.llm.cache and cache_file.exists():
            try:
                cache_data = json.loads(cache_file.read_text(encoding="utf-8"))
                cue.target_text = cache_data.get("text", "")
                translated_records.append(
                    {
                        "id": cue.id,
                        "text": cue.target_text,
                        "model": cfg.llm.model or "default",
                        "prompt_version": prompt_version,
                        "glossary_version": glossary_version,
                        "cached": True,
                        "tokens": len(cue.target_text or ""),
                    }
                )
                continue
            except Exception:
                pass
        uncached_cues.append(cue)

    # Step 2: Batch uncached items
    batches = build_batches(uncached_cues, cfg)
    for b_idx, batch in enumerate(batches):
        # Determine context before and after
        first_id = batch[0].id
        last_id = batch[-1].id
        ctx_before = [cue_map[i].text for i in range(max(0, first_id - 3), first_id)]
        ctx_after = [cue_map[i].text for i in range(last_id + 1, min(len(cues), last_id + 4))]

        glossary_payload = [g.model_dump(mode="json") for g in glossary]
        payload = {
            "task": "subtitle_translation",
            "source_lang": job.source_lang or "auto",
            "target_lang": job.target_lang,
            "context_before": ctx_before,
            "context_after": ctx_after,
            "glossary": glossary_payload,
            "items": [{"id": c.id, "text": c.text} for c in batch],
        }

        mapping = _translate_batch_with_retry(
            client=client,
            system=system_prompt,
            payload=payload,
            batch_cues=batch,
            retries=cfg.llm.max_retries,
        )

        for cue in batch:
            target_t = mapping.get(cue.id, "")
            cue.target_text = target_t

            # Write cache
            if cfg.llm.cache:
                k = cache_key(
                    model=cfg.llm.model or "default",
                    prompt_version=prompt_version,
                    glossary_version=glossary_version,
                    source_lang=job.source_lang or "auto",
                    target_lang=job.target_lang,
                    text=cue.text,
                )
                cache_payload = {
                    "text": target_t,
                    "model": cfg.llm.model or "default",
                    "created_at": time.time(),
                }
                (cache_dir / f"{k}.json").write_text(
                    json.dumps(cache_payload, ensure_ascii=False), encoding="utf-8"
                )

            translated_records.append(
                {
                    "id": cue.id,
                    "text": target_t,
                    "model": cfg.llm.model or "default",
                    "prompt_version": prompt_version,
                    "glossary_version": glossary_version,
                    "cached": False,
                    "tokens": len(target_t),
                }
            )

    # Invariance check: timecodes MUST NOT CHANGE
    for cue in cues:
        orig = orig_timecodes[cue.id]
        if (cue.start, cue.end) != orig:
            raise AssertionError(
                f"Timecode changed for cue {cue.id}: was {orig}, now {(cue.start, cue.end)}"
            )

    translated_records.sort(key=lambda r: r["id"])
    return cues, translated_records


def run(job: Job, cfg: Config) -> StageResult:
    start_t = time.monotonic()
    work_job = cfg.work_dir / job.job_id
    cues_file = work_job / "20_cues.jsonl"
    if not cues_file.exists():
        raise FileNotFoundError(f"missing 20_cues.jsonl for job {job.job_id}")

    cues = read_jsonl(cues_file, model=Cue)
    _, glossary = load_glossary(cfg.root)

    cues, records = translate_cues(cues, glossary, cfg, job)
    write_jsonl(work_job / "30_translated.jsonl", records)
    # Also update 20_cues.jsonl with backfilled target_text for downstream
    write_jsonl(cues_file, cues)

    return StageResult(
        stage="translate",
        ok=True,
        count=len(records),
        duration_sec=round(time.monotonic() - start_t, 2),
    )
