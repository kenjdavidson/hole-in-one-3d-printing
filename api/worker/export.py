"""Blender export utilities.

Provides :func:`export_result` as the single public entry point.  Internally
this module delegates to :func:`_export_blend` or :func:`_export_stl`,
keeping all format-specific logic isolated.

STL layer grouping
------------------
Objects from the output collection are bucketed into per-colour-prefix files:

* ``base_and_text.stl`` – ``Hole_In_One_Base`` + all ``Text.*`` objects
* ``water.stl``    – all ``Water.*`` objects
* ``sand.stl``     – all ``Sand.*`` objects
* ``green.stl``    – all ``Green.*`` objects
* ``tee.stl``      – all ``Tee.*`` objects
* ``fairway.stl``  – all ``Fairway.*`` objects
* ``rough.stl``    – all ``Rough.*`` objects
* ``misc.stl``     – anything that doesn't match a known prefix
"""

import os

# Map generation mode to the Blender collection that holds its output objects.
# String literals avoid importing golf.config before sys.path is ready.
_COLLECTION_BY_MODE: dict[str, str] = {
    "engrave": "Hole_In_One_Output",
    "insert":  "Hole_In_One_Inserts",
    "topology": "Hole_In_One_Output",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def export_result(fmt: str, mode: str, output_dir: str) -> None:
    """Export the generated scene to *output_dir* in the requested format.

    Args:
        fmt:        ``"blend"`` or ``"stl"``.
        mode:       ``"engrave"`` or ``"insert"`` (used to select the correct
                    Blender collection when exporting STL files).
        output_dir: Directory where output files are written.
    """
    if fmt == "blend":
        _export_blend(output_dir)
    else:
        _export_stl(output_dir, mode)


# ---------------------------------------------------------------------------
# Blend export
# ---------------------------------------------------------------------------


def _export_blend(output_dir: str) -> None:
    """Save the entire Blender scene as ``result.blend`` in *output_dir*."""
    import bpy

    blend_path = os.path.join(output_dir, "result.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    print(f"[worker:export] Saved .blend: {blend_path}")


# ---------------------------------------------------------------------------
# STL export
# ---------------------------------------------------------------------------


def _export_stl(output_dir: str, mode: str) -> None:
    """Export mesh objects to per-layer-group STL files in *output_dir*."""
    import bpy

    candidates = _collect_mesh_objects(mode)
    if not candidates:
        print("[worker:export] WARNING: no exportable mesh objects found")
        return

    groups = _group_by_layer(candidates)
    summary = ", ".join(f"{g}({len(objs)})" for g, objs in groups.items())
    print(f"[worker:export] STL export groups: {summary}")

    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

    for group_name, objects in groups.items():
        filepath = os.path.join(output_dir, f"{group_name}.stl")
        _select_objects(objects)
        _invoke_stl_exporter(filepath, use_selection=True)
        print(f"[worker:export] Exported: {filepath}")


def _collect_mesh_objects(mode: str) -> list:
    """Return visible mesh objects from the mode's output collection.

    Falls back to all visible scene meshes if the collection is missing.
    """
    import bpy

    collection_name = _COLLECTION_BY_MODE.get(mode, "Hole_In_One_Output")
    collection = bpy.data.collections.get(collection_name)

    if collection is not None:
        return [o for o in collection.objects if o.type == "MESH" and not o.hide_render]

    print(
        f"[worker:export] WARNING: collection '{collection_name}' not found; "
        "falling back to all visible mesh objects"
    )
    return [o for o in bpy.data.objects if o.type == "MESH" and not o.hide_render]


def _group_by_layer(objects: list) -> dict[str, list]:
    """Bucket *objects* into named groups by their colour-prefix."""
    groups: dict[str, list] = {}
    for obj in objects:
        group = _layer_group_name(obj.name)
        groups.setdefault(group, []).append(obj)
    return groups


def _layer_group_name(obj_name: str) -> str:
    """Map a Blender object name to an STL export-group label."""
    from golf.config import BASE_OBJECT_NAME, COLOR_MAP  # noqa: PLC0415

    if obj_name == BASE_OBJECT_NAME or obj_name.startswith("Text"):
        return "base_and_text"

    for prefix in COLOR_MAP:
        if obj_name.startswith(prefix):
            return prefix.lower()

    return "misc"


def _select_objects(objects: list) -> None:
    """Deselect all, then select *objects* and make the first one active."""
    import bpy

    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]


def _invoke_stl_exporter(filepath: str, use_selection: bool) -> None:
    """Call the appropriate STL export operator for the running Blender version.

    Blender 3.3+ ships the built-in ``wm.stl_export``; older builds used the
    legacy ``export_mesh.stl`` add-on.
    """
    import bpy

    if hasattr(bpy.ops.wm, "stl_export"):
        bpy.ops.wm.stl_export(
            filepath=filepath,
            export_selected_objects=use_selection,
            ascii_format=False,
            apply_modifiers=True,
        )
    else:
        bpy.ops.export_mesh.stl(
            filepath=filepath,
            use_selection=use_selection,
            use_mesh_modifiers=True,
        )
