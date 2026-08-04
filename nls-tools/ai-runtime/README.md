# NJS AI runtime — light workers

This directory contains the shared, reproducible runtime contract for the
SAM2, RMBG-2.0 and LaMa workers. It implements the infrastructure part of the
AI image-editing plan; it is not the future NJS AI Gateway.

## Scope against the implementation plan

This setup completes the common `light` worker foundation: portable storage
configuration, pinned images/source revisions, verified model artifacts,
versioned workflows, GPU/readiness checks and equivalent Windows/Linux launch
paths.

It deliberately does not implement the remaining end-to-end architecture:

- the `core` profile with NJS AI Gateway, queue and job persistence;
- domain endpoints, async jobs, progress/SSE, cancellation, retry and global
  one-GPU-job scheduling;
- asset transfer and lineage through `njs-zdjecia`;
- the `heavy` FLUX.2 worker/profile;
- the desktop editor and its undo/redo/materialization flow.

Until the Gateway story is complete, these ports are development and worker
diagnostics only. The production desktop must not call ComfyUI or IOPaint
directly.

## Stability rules

- Git dependencies are fetched from configurable primary/mirror repositories
  and the resulting checkout must match the pinned full commit.
- Model files are prepared before a production container starts. Every file
  has a fixed size and SHA-256 in `models/*.json`.
- A verified file already present in the download cache or an explicitly
  configured import root is reused before any network request.
- Download URLs use immutable revisions where the upstream supports them.
  `NJS_AI_MODEL_MIRROR` can point at an internal HTTPS mirror or local folder.
- Containers run with read-only model mounts. A missing or modified model
  makes readiness fail instead of triggering an uncontrolled download.
- Worker ports bind to `127.0.0.1` by default. The future Gateway should reach
  them through the external Docker network `njs-ai`.

## Windows GPU setup

Copy the appropriate example as the ignored `.env` file and review it. The
generic `.env.example` has intentionally empty storage roots;
`.env.windows-ai-pc.example` is only a convenience preset for the current AI
workstation. Do not acknowledge a checkpoint license without confirming that
it covers the intended use.

Compose definitions contain no fallback host path. The three storage roots are
required configuration, so moving the repository to another Windows/Linux
host cannot silently create or mount a path copied from another machine. A host
chooses its own absolute roots. `NJS_AI_REQUIRE_D_DRIVE` is an optional local
guard, not part of the worker contract.

Each worker start script invokes `Initialize-NjsAiRuntime.ps1`, which:

1. creates persistent directories below the configured roots;
2. validates or prepares all required model files;
3. creates the shared `njs-ai` Docker network;
4. starts a `light` profile and waits for container readiness;
5. runs a read-only API smoke test.

To validate, build and start the whole Windows `light` profile in one command:

```powershell
.\nls-tools\ai-runtime\scripts\Start-NjsAiLightWorkers.ps1
```

Individual worker scripts remain available for focused development.

The layout is stable relative to configuration, not to a drive or mount point:

```text
${NJS_AI_MODELS_ROOT}/...                 immutable model artifacts
${NJS_AI_CACHE_ROOT}/...                  downloads and per-worker caches
${NJS_AI_DATA_ROOT}/workers/<worker>/...  isolated input/output/user/temp
```

`NJS_AI_MODEL_IMPORT_ROOTS` can point to existing model stores. The preparer
only imports files matching the manifest checksum, copies them into the chosen
model root and never deletes the source.

## Linux GPU setup

Copy `.env.linux.example` to the ignored `.env`, review the paths and license
gates, then run:

```bash
./nls-tools/ai-runtime/scripts/start-light-workers.sh
```

The script prepares pinned artifacts, validates all three Compose definitions,
starts the `light` workers and runs the same API smoke tests as Windows. The
public worker contract, image versions, workflows and checkpoint hashes remain
identical on both hosts. Configure `NJS_AI_BIND_ADDRESS` only when deliberate
access from a private/VPN address is needed; the default is loopback.

## Manual verification

```powershell
python .\nls-tools\ai-runtime\scripts\smoke_light_workers.py all
```

```bash
python3 nls-tools/ai-runtime/scripts/smoke_light_workers.py all
```

This confirms CUDA visibility and required ComfyUI nodes for SAM2/RMBG2, and
confirms that IOPaint reports the LaMa model. It does not replace the planned
fixture-based quality benchmark or Gateway contract tests.

## License gates

- SAM2 code and checkpoint are recorded as Apache-2.0.
- BRIA RMBG-2.0 self-hosted weights are non-commercial unless a separate
  commercial agreement applies. `NJS_RMBG2_LICENSE_ACCEPTED=1` is required.
- The LaMa code license does not by itself establish the terms of the exact
  Big-LaMa checkpoint. `NJS_BIG_LAMA_LICENSE_ACCEPTED=1` is required after a
  separate review.
