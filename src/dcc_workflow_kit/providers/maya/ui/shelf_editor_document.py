# SPDX-License-Identifier: GPL-3.0-or-later
"""shelves.json handling for the Shelf Editor: a deep copy of the user's shelf document (``_copy_document``), an
atomic write that reads the file back to verify it (``_write_document_atomic``) and the three-way merge of the
editor's draft with changes made elsewhere while it was open (``_merge_documents``: editor edits win, outside
additions and deletions stay). Related: shelf_editor_draft.py (Save), shelf_store.py."""

import json
import os
import tempfile

from . import shelf


def _copy_document():
    return json.loads(json.dumps(shelf.user_data()))


def _write_document_atomic(document):
    """Persist a complete shelves.json document atomically and verify the result."""
    path = shelf.store_path()
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n",
                dir=folder, prefix=".shelves-", suffix=".tmp",
                delete=False) as stream:
            temp_path = stream.name
            json.dump(document, stream, indent=1, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())

        with open(temp_path, "r", encoding="utf-8") as stream:
            check = json.load(stream)
        if check != document:
            raise ValueError("Shelf data verification failed before save")

        os.replace(temp_path, path)
        temp_path = None

        with open(path, "r", encoding="utf-8") as stream:
            saved = json.load(stream)
        if saved != document:
            raise ValueError("Saved Shelf data does not match the draft")
        return saved
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def _merge_button_lists(base, draft, latest):
    """Merge button sequences while keeping the editor draft authoritative for deletions."""
    from difflib import SequenceMatcher

    base = json.loads(json.dumps(base or []))
    draft = json.loads(json.dumps(draft or []))
    latest = json.loads(json.dumps(latest or []))

    def mapping(source):
        matched = {}
        extras = []
        # Button records are dictionaries, which SequenceMatcher cannot hash.
        # Compare stable JSON signatures while keeping the original records in
        # ``source`` for the merge result below.
        signatures = lambda records: [json.dumps(
            record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            for record in records]
        matcher = SequenceMatcher(a=signatures(base), b=signatures(source), autojunk=False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                for offset in range(i2 - i1):
                    matched[i1 + offset] = j1 + offset
            elif tag == "replace":
                shared = min(i2 - i1, j2 - j1)
                for offset in range(shared):
                    matched[i1 + offset] = j1 + offset
                # New entries in a replace range are retained as additions.
                extras.extend(source[j1 + shared:j2])
            elif tag == "insert":
                extras.extend(source[j1:j2])
        return matched, extras

    draft_map, _draft_extras = mapping(draft)
    live_map, live_extras = mapping(latest)
    merged = json.loads(json.dumps(draft))

    # Deletions made in the editor are already absent from ``merged`` (a copy of the draft). A record
    # deleted from the live shelf while the editor was open stays deleted when the editor left it
    # unchanged; a record edited in the editor is kept (the edit wins over the live deletion).
    deleted_live = {draft_map[b] for b in range(len(base))
                    if b not in live_map and b in draft_map
                    and draft_map[b] < len(draft) and draft[draft_map[b]] == base[b]}

    # Adopt external edits only where the corresponding draft entry is still unchanged.
    for base_index, live_index in live_map.items():
        draft_index = draft_map.get(base_index)
        if draft_index is None or draft_index >= len(draft) or live_index >= len(latest):
            continue
        if draft[draft_index] == base[base_index] and latest[live_index] != base[base_index]:
            if 0 <= draft_index < len(merged):
                merged[draft_index] = latest[live_index]

    merged = [record for index, record in enumerate(merged) if index not in deleted_live]
    # Preserve external additions (Ctrl+Shift-click, gear menu, settings import).
    merged.extend(json.loads(json.dumps(live_extras)))
    return merged

def _merge_mapping(base, draft, latest):
    """Merge record fields; preserve live values the editor did not modify."""
    result = json.loads(json.dumps(latest))
    missing = object()
    for key in set(base) | set(draft):
        before = base.get(key, missing)
        after = draft.get(key, missing)
        if after == before:
            continue
        if after is missing:
            result.pop(key, None)
        else:
            result[key] = json.loads(json.dumps(after))
    return result


def _merge_shelves(base_shelves, draft_shelves, latest_shelves):
    base_by = {item.get("name"): item for item in base_shelves or []}
    draft_by = {item.get("name"): item for item in draft_shelves or []}
    latest_by = {item.get("name"): item for item in latest_shelves or []}
    merged = []
    for item in draft_shelves or []:
        name = item.get("name")
        before = base_by.get(name)
        latest = latest_by.get(name)
        if before is not None and latest is None:
            # A Shelf deleted from the live settings UI while this editor was open stays deleted.
            continue
        if before is not None and latest is not None:
            current = _merge_mapping(before, item, latest)
            current["buttons"] = _merge_button_lists(
                before.get("buttons", []), item.get("buttons", []), latest.get("buttons", []))
            merged.append(current)
        else:
            merged.append(json.loads(json.dumps(item)))
    for item in latest_shelves or []:
        name = item.get("name")
        if name not in base_by and name not in draft_by:
            merged.append(json.loads(json.dumps(item)))
    return merged


def _merge_documents(base, draft, latest):
    """Three-way merge a Shelf Editor draft with the latest shelves.json document."""
    base, draft, latest = base or {}, draft or {}, latest or {}
    result = json.loads(json.dumps(latest))
    result["shelves"] = _merge_shelves(
        base.get("shelves", []), draft.get("shelves", []), latest.get("shelves", []))
    base_extra = base.get("extra", {}) or {}
    draft_extra = draft.get("extra", {}) or {}
    latest_extra = latest.get("extra", {}) or {}
    extra = json.loads(json.dumps(latest_extra))
    for shelf_id in set(base_extra) | set(draft_extra) | set(latest_extra):
        before = base_extra.get(shelf_id, [])
        after = draft_extra.get(shelf_id, [])
        live = latest_extra.get(shelf_id, [])
        if after != before:
            extra[shelf_id] = _merge_button_lists(before, after, live)
    if extra:
        result["extra"] = extra
    for key in set(base) | set(draft):
        if key in {"shelves", "extra"}:
            continue
        if draft.get(key) != base.get(key):
            if key in draft:
                result[key] = json.loads(json.dumps(draft[key]))
            else:
                result.pop(key, None)
    return result
