# SPDX-License-Identifier: GPL-3.0-or-later
"""The user's own key edits that the Maya keys come and go with (GitHub #363).

Blender keeps the user's keymap edits (Preferences > Keymap, the kit's Hotkey Editor) as differences from the item
each edit was made on, found again by operator, properties and key. Two kinds of item are not always there:

- the Maya keys are add-on keymap items that exist only while the Maya keys are on, and their operators only while
  Maya mode is on. An edit of a Maya key whose operator has properties lost them when the operator went away, so
  Maya mode off / on (or a restart in Blender mode) gave the kit's own key back;
- Blender's own items of the keymaps the Maya keys replace are switched off while the Maya keys are on, so an edit
  made to one of them in Blender mode was dropped as soon as another key of that keymap changed in Maya mode.

So when the Maya keys go out, the user's edits of them (changed, removed, and keys the user added for kit commands)
are written into the add-on preferences (``user_keys``) and taken out of the user keymap; when the Maya keys come
back, they are given again on the user keymap items, the way Preferences > Keymap changes an item. The edits of
Blender's items are kept and taken out of the user keymap from Maya keys on until off (else they land on the equal
Maya keys, #544), then given back. A key is only given back
while the item is as the kit / Blender made it, so an edit Blender kept itself always wins. Nothing else changes:
the record holds only what the user changed, and it is empty (unset) when there is nothing to keep.

Many Maya keys are the same item as a Blender key (Undo on Ctrl+Z), and Blender keeps a keymap edit as "change / remove
the item equal to this one", applied to the first equal item it finds. So a Maya key the user removed would remove
Blender's own key once the Maya keys are gone: taking the edits out leaves no such edit behind (``reset_keymap``),
and Blender mode always has Blender's keys.
"""

import json

import bpy

KIT_PREFIX = "allset."
# modifiers this Blender has on keymap items (Hyper is newer than some supported versions)
MODIFIERS = tuple(m for m in ("shift", "ctrl", "alt", "oskey", "hyper")
                  if m in bpy.types.KeyMapItem.bl_rna.properties)
FIELDS = ("idname", "type", "value", "any", *MODIFIERS, "key_modifier", "direction", "repeat", "active")


# --- items as plain data -------------------------------------------------------------------------------------------

def _plain(value):
    if isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    try:
        return [_plain(v) for v in value]
    except TypeError:
        return None


def _props(kmi):
    """The operator properties set on the item, as JSON values (pointer / collection properties are left out)."""
    p = kmi.properties
    if p is None:
        return {}
    out = {}
    for prop in p.bl_rna.properties:
        name = prop.identifier
        if name == "rna_type" or prop.type in {'POINTER', 'COLLECTION'} or not p.is_property_set(name):
            continue
        value = _plain(getattr(p, name))
        if value is not None:
            out[name] = value
    return out


def state(kmi):
    """Everything about a keymap item a user can change, as JSON data."""
    out = {f: getattr(kmi, f) for f in FIELDS}
    out["props"] = _props(kmi)
    return out


def _norm(st):
    """Comparable form: float noise (float32 storage) and the order of properties don't count."""
    def n(v):
        if isinstance(v, float):
            return round(v, 4)
        if isinstance(v, list):
            return tuple(n(x) for x in v)
        return v
    props = tuple(sorted((k, n(v)) for k, v in (st.get("props") or {}).items()))
    return tuple(n(st.get(f)) for f in FIELDS) + (props,)


def same(a, b):
    return _norm(a) == _norm(b)


def write(kmi, st):
    """Give a keymap item this state (like editing it in Preferences > Keymap)."""
    if kmi.idname != st["idname"]:
        kmi.idname = st["idname"]
    for f in ("type", "value", "key_modifier", "direction", "repeat", "active"):
        if f in st and getattr(kmi, f) != st[f]:
            setattr(kmi, f, st[f])
    if st.get("any"):
        kmi.any = True
    else:
        if kmi.any:
            kmi.any = False
        for m in MODIFIERS:
            if m in st and getattr(kmi, m) != st[m]:
                setattr(kmi, m, st[m])
    p = kmi.properties
    for name, value in (st.get("props") or {}).items():
        if p is None:
            break
        rna = p.bl_rna.properties.get(name)
        if rna is None:
            continue
        try:
            setattr(p, name, set(value) if getattr(rna, "is_enum_flag", False) else value)
        except (TypeError, ValueError, AttributeError):
            pass                     # the operator changed since the edit was kept


# --- the record in the add-on preferences --------------------------------------------------------------------------

def _prefs():
    from .. import preferences
    try:
        return preferences.get()
    except (KeyError, AttributeError):
        return None


def load():
    """{"maya": [...], "blender": [...]} (empty lists when nothing is kept)."""
    p = _prefs()
    raw = p.user_keys if p is not None else ""
    try:
        data = json.loads(raw) if raw else {}
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    return {"maya": list(data.get("maya") or ()), "blender": list(data.get("blender") or ())}


def save(record):
    p = _prefs()
    if p is None:
        return
    keep = {k: v for k, v in record.items() if v}
    if not keep:
        if p.is_property_set("user_keys"):
            p.property_unset("user_keys")
        return
    raw = json.dumps(keep, sort_keys=True, separators=(",", ":"))
    if p.user_keys != raw:
        p.user_keys = raw


# --- matching ------------------------------------------------------------------------------------------------------

def _find(keymaps, name, space, region):
    return keymaps.find(name, space_type=space, region_type=region)


def _where(km):
    return km.name, km.space_type, km.region_type


def _bases(km, keep=None):
    """[(item, state, n)] of a base keymap's items (``keep(item)`` filters), n = how many items with the same state
    come before it (two identical items are told apart by their order)."""
    out, seen = [], {}
    for kmi in km.keymap_items:
        if keep is not None and not keep(kmi):
            continue
        st = state(kmi)
        key = _norm(st)
        out.append((kmi, st, seen.get(key, 0)))
        seen[key] = seen.get(key, 0) + 1
    return out


def _edits(base_km, user_km, keep=None):
    """Entries for the base keymap's items the user changed or removed in the user keymap."""
    name, space, region = _where(base_km)
    out = []
    for kmi, st, n in _bases(base_km, keep):
        user = user_km.keymap_items.find_match(base_km, kmi)
        if user is None:
            out.append({"km": name, "space": space, "region": region, "base": st, "n": n, "state": None})
            continue
        now = state(user)
        if not same(now, st):
            out.append({"km": name, "space": space, "region": region, "base": st, "n": n, "state": now})
    return out


def _user_item(base_km, user_km, bases, e):
    """The user keymap item of the entry's base item (None: the kit / Blender no longer has that key, or the
    user removed it)."""
    base = e.get("base") or {}
    kmi = next((k for k, st, n in bases if n == e.get("n") and same(st, base)), None)
    return user_km.keymap_items.find_match(base_km, kmi) if kmi is not None else None


def _give(base_km, user_km, entries, keep=None):
    """Give the entries back on the user keymap items whose base item is still as it was (an item Blender
    already shows edited is left alone). Returns the number of items changed."""
    bases = _bases(base_km, keep)
    done = 0
    for e in entries:
        user = _user_item(base_km, user_km, bases, e)
        if user is None or not same(state(user), e["base"]):
            continue
        if e.get("state") is None:
            user_km.keymap_items.remove(user)
        else:
            write(user, e["state"])
        done += 1
    return done


def _ready(kcs, keymaps):
    """The keyconfigs are built: the active keyconfig has some of these keymaps ([(name, space, region)]) and the
    user keyconfig every one of those (at startup the preset and the user keymaps come after the add-ons)."""
    kc, user = kcs.active, kcs.user
    if kc is None or user is None or kcs.addon is None:
        return False
    present = [w for w in keymaps if _find(kc.keymaps, *w) is not None]
    return bool(present) and all(_find(user.keymaps, *w) is not None for w in present)


def _group(entries):
    out = {}
    for e in entries:
        out.setdefault((e.get("km"), e.get("space"), e.get("region")), []).append(e)
    return out


# --- the Maya keys (add-on keyconfig items) ----------------------------------------------------------------------

def _kit_keymaps(kcs, ptrs):
    return [km for km in kcs.addon.keymaps if any(k.as_pointer() in ptrs for k in km.keymap_items)]


def capture_maya(kcs, ptrs):
    """The user's edits of the Maya keys (``ptrs`` = the kit's add-on items) and the keys the user added for kit
    commands. None when the user keyconfig doesn't hold the Maya keys (not built yet, Blender quitting)."""
    if kcs.addon is None or kcs.user is None:
        return None
    kcs.update()
    kit_kms = _kit_keymaps(kcs, ptrs)
    if not _ready(kcs, [_where(km) for km in kit_kms]):
        return None
    entries = []
    for akm in kit_kms:
        ukm = _find(kcs.user.keymaps, *_where(akm))
        if ukm is not None and ukm.is_user_modified:
            entries += _edits(akm, ukm, keep=lambda k: k.as_pointer() in ptrs)
    for ukm in kcs.user.keymaps:
        if not ukm.is_user_modified or ukm.is_modal:
            continue
        name, space, region = _where(ukm)
        for kmi in ukm.keymap_items:
            if kmi.is_user_defined and kmi.idname.startswith(KIT_PREFIX):
                entries.append({"km": name, "space": space, "region": region, "added": state(kmi)})
    return entries


def take_out_maya(kcs, ptrs, entries):
    """The user keymap without the entries' edits (Blender would otherwise keep differences to keys that are about
    to go, and lose the properties of kit commands with them, or apply them to Blender's own equal keys)."""
    for (name, space, region), group in _group(entries).items():
        ukm = _find(kcs.user.keymaps, name, space, region)
        akm = _find(kcs.addon.keymaps, name, space, region)
        if ukm is None:
            continue
        bases = _bases(akm, keep=lambda k: k.as_pointer() in ptrs) if akm is not None else []
        removed = False
        for e in group:
            if "added" in e:
                kmi = next((k for k in ukm.keymap_items if k.is_user_defined and same(state(k), e["added"])), None)
                if kmi is not None:
                    ukm.keymap_items.remove(kmi)
            elif e.get("state") is not None and akm is not None:
                kmi = _user_item(akm, ukm, bases, e)
                if kmi is not None and same(state(kmi), e["state"]):
                    ukm.restore_item_to_default(kmi)
            else:
                removed = True
        if removed:
            reset_keymap(kcs, ptrs, name, space, region)
    kcs.update()


def reset_keymap(kcs, ptrs, name, space, region):
    """A removed Maya key stays in Blender's keymap edits as "remove the item equal to this one", which with the Maya
    keys gone is Blender's own item of the same key, and Blender has no way to take back one removal. So the keymap
    goes back to its items and the user's other edits of it are given again: Blender's items, other add-ons' items,
    keys the user added (the Maya keys' own edits are already in the entries). The Hotkey Editor's Restore All uses it
    too: a Maya key switched off or removed in Preferences > Keymap has no item of its own to restore."""
    kcs.update()
    ukm = _find(kcs.user.keymaps, name, space, region)
    akm = _find(kcs.addon.keymaps, name, space, region)
    bkm = _find(kcs.active.keymaps, name, space, region) if kcs.active is not None else None
    if ukm is None:
        return

    def others(k):
        return k.as_pointer() not in ptrs
    blender = _edits(bkm, ukm) if bkm is not None else []
    addons = _edits(akm, ukm, keep=others) if akm is not None else []
    added = [state(k) for k in ukm.keymap_items if k.is_user_defined]
    ukm.restore_to_default()
    kcs.update()
    ukm = _find(kcs.user.keymaps, name, space, region)
    if ukm is None:
        return
    if bkm is not None and blender:
        _give(bkm, ukm, blender)
    if akm is not None and addons:
        _give(akm, ukm, addons, keep=others)
    for st in added:
        write(ukm.keymap_items.new(st["idname"], st["type"], st["value"]), st)


def restore_items(kcs, ptrs, name, space, region, back):
    """Give the Maya keys ``back`` (add-on item pointers of one keymap) the kit's key again when the user keymap no
    longer shows them (switched off or removed in Preferences > Keymap, see ``reset_keymap``): the keymap is reset and
    every other edit of it is given again, the other Maya keys' edits included."""
    akm = _find(kcs.addon.keymaps, name, space, region)
    ukm = _find(kcs.user.keymaps, name, space, region)
    if akm is None or ukm is None:
        return False

    def kit(k):
        return k.as_pointer() in ptrs
    skip = {(_norm(st), n) for k, st, n in _bases(akm, kit) if k.as_pointer() in back}
    rest = [e for e in _edits(akm, ukm, keep=kit) if (_norm(e["base"]), e["n"]) not in skip]
    reset_keymap(kcs, ptrs, name, space, region)
    ukm = _find(kcs.user.keymaps, name, space, region)
    if ukm is not None and rest:
        _give(akm, ukm, rest, keep=kit)
    kcs.update()
    return True


def put_back_maya(kcs, ptrs, entries):
    """Give the kept edits of the Maya keys again. False when the user keyconfig doesn't hold the Maya keys yet."""
    if kcs.addon is None or kcs.user is None:
        return False
    kcs.update()
    if not _ready(kcs, [_where(km) for km in _kit_keymaps(kcs, ptrs)]):
        return False
    for (name, space, region), group in _group(entries).items():
        akm = _find(kcs.addon.keymaps, name, space, region)
        ukm = _find(kcs.user.keymaps, name, space, region)
        if ukm is None:
            continue
        added = [e["added"] for e in group if "added" in e]
        for st in added:
            have = [k for k in ukm.keymap_items if k.is_user_defined and k.idname == st.get("idname")
                    and k.type == st.get("type") and k.value == st.get("value")]
            if any(same(state(k), st) for k in have):
                continue
            kmi = have[0] if have else ukm.keymap_items.new(st["idname"], st["type"], st["value"])
            write(kmi, st)
        if akm is not None:
            _give(akm, ukm, [e for e in group if "added" not in e], keep=lambda k: k.as_pointer() in ptrs)
    kcs.update()
    return True


# --- Blender's own items of the keymaps the Maya keys switch off ---------------------------------------------------

def capture_blender(kcs, names):
    """The user's edits of the active keyconfig's items in these keymaps ([(name, space, region)]); None when the
    user keyconfig isn't built yet."""
    if kcs.user is None:
        return None
    kcs.update()
    if not _ready(kcs, names):
        return None
    kc, user = kcs.active, kcs.user
    entries = []
    for name, space, region in names:
        bkm = _find(kc.keymaps, name, space, region)
        ukm = _find(user.keymaps, name, space, region)
        if bkm is not None and ukm is not None and ukm.is_user_modified:
            entries += _edits(bkm, ukm)
    for e in entries:
        e["keyconfig"] = kc.name
    return entries


def take_out_blender(kcs, entries):
    """The user keymap without the entries' edits of Blender's items, before the Maya keys go on (#544): Blender
    applies a keymap edit to the first item equal to the edited one, and the Maya keys come in front of Blender's
    items, so an edit made in Blender mode (a key switched off, changed or removed) would land on the Maya key of the
    same event: the mouse wheel switched off in Blender mode stopped zooming in Maya mode too. Each keymap goes back
    to its items and the user's other edits of it are given again (other add-ons' items, keys the user added); the
    entries come back with ``put_back_blender`` when the Maya keys go out."""
    for name, space, region in _group(entries):
        kcs.update()
        ukm = _find(kcs.user.keymaps, name, space, region)
        if ukm is None or not ukm.is_user_modified:
            continue
        akm = _find(kcs.addon.keymaps, name, space, region)
        addons = _edits(akm, ukm) if akm is not None else []
        added = [state(k) for k in ukm.keymap_items if k.is_user_defined]
        ukm.restore_to_default()
        kcs.update()
        ukm = _find(kcs.user.keymaps, name, space, region)
        if ukm is None:
            continue
        if akm is not None and addons:
            _give(akm, ukm, addons)
        for st in added:
            write(ukm.keymap_items.new(st["idname"], st["type"], st["value"]), st)
    kcs.update()


def put_back_blender(kcs, entries):
    """Give back the kept edits of Blender's items that a change in Maya mode dropped. None when the user
    keyconfig isn't built (nothing done, keep the entries)."""
    if kcs.user is None:
        return None
    kcs.update()
    if not _ready(kcs, [(e.get("km"), e.get("space"), e.get("region")) for e in entries]):
        return None
    kc, user = kcs.active, kcs.user
    done = 0
    for (name, space, region), group in _group(e for e in entries if e.get("keyconfig") == kc.name).items():
        bkm = _find(kc.keymaps, name, space, region)
        ukm = _find(user.keymaps, name, space, region)
        if bkm is not None and ukm is not None:
            done += _give(bkm, ukm, group)
    if done:
        kcs.update()
    return done
