# Original projects and modifications

This independent integration is not an official Autodesk, Blender Foundation, Blender Max or Maya Workflow Kit release.

## Blender Max

- Project: https://github.com/neom315/blender-max
- Website/release source: https://neom315.github.io/blender-max/blender_max-0.6.8.zip
- Version: 0.6.8, original archive SHA-256 `9eef8f1da471e14b8c7a415e438cbddb3994a6f94c1c321c09caa9ba7cb8adde`.
- Attribution: Blender Max contributors, as declared in the original extension manifest.
- Code/license declaration: GPL-3.0-or-later. The original LICENSE is retained in providers/max/LICENSE and at the package root.
- Integration changes: lifecycle and preferences adapters, exclusive mode switching, Blender 5.1/5.2 loop-selection compatibility, disabling undocumented layout memory access, removing scene defaults from UI switching, Chinese localization and font fallback.

## Maya Workflow Kit

- Original project: https://github.com/5hyuns/maya-workflow-kit-for-blender
- Original author: ohnsk / 5hyuns; upstream revision `bd7ee0440250bf00d57c7aa304dd8cabc8b03143`, upstream 0.6.2.
- Simplified Chinese localization: namink, 2026-10-29, local version 0.6.2+zh.2. See MAYA_LOCALIZATION.md and MAYA_UPSTREAM.json.
- Python code: GPL-3.0-or-later. Original LICENSE remains providers/maya/LICENSE.
- Original non-code assets: CC0-1.0, limited to files declared in providers/maya/ASSETS_LICENSE.txt; that file remains authoritative.
- Integration changes: unified settings/identity and switch routing; split persistent schemas/scene solvers from interactive hooks; retain/reuse Maya workspaces; remove implicit startup-scene replacement; scoped icon/shelf paths; transactional mode registration; minor additional Chinese UI entries.

## Localization inputs

Existing Maya translations are retained. Some Max labels reuse exact matching entries from the locally installed Blender Simplified Chinese GNU gettext catalog (Blender GPL licensing), with Max-specific terminology overrides. The output catalog is included as editable JSON. Autodesk's public Chinese documentation is used as terminology reference; no Autodesk source code or proprietary fonts/assets are included by this integration.

Version 0.1.1 expands both catalogs with local translation-memory matches, public UI translation drafts, individually translated unresolved entries and domain terminology corrections. This is a maintenance-time process; the installed extension performs no online translation. See LOCALIZATION_REPORT.md and localization-review in the source project for scope and review records.

Translations of Max Command Panel, Modifier Stack, Quad Menu and Maya Channel Box, Attribute Editor, Construction History, Freeze Transformations retain separate meanings. Broader terminology review remains in progress; no claim of complete official-language equivalence is made.

## Reproducibility

UPSTREAM_HASHES.json at the source-project root records the imported Python file hashes. Imported providers have subsequently been adapted; these hashes describe the baseline, not current files. tools/import_sources.py, tools/localize_max.py and tools/mark_max_messages.py document initial transformation steps, not an overwrite-safe updater. Do not rerun them on an edited provider tree. Build the current reviewed source with tools/build.py.

Autodesk, 3ds Max and Maya are trademarks of their respective owners. No affiliation, endorsement or sponsorship is claimed.
