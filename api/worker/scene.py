"""Blender scene initialisation and SVG import."""


def setup_scene() -> None:
    """Reset Blender to an empty scene.

    Discards the default startup file (cube, camera, light) so that imported
    SVG objects are the only things in the scene.
    """
    import bpy

    bpy.ops.wm.read_homefile(use_empty=True)


def import_svg(filepath: str) -> None:
    """Import *filepath* into the current Blender scene.

    Blender's SVG importer creates ``CURVE`` objects whose names match the SVG
    layer / group names (e.g. ``Water.001``, ``Text.002``).  The golf pipeline
    selects objects by these name prefixes.
    """
    import bpy

    print(f"[worker:scene] Importing SVG: {filepath}")
    bpy.ops.import_curve.svg(filepath=filepath)

    imported = [o.name for o in bpy.data.objects if o.type in {"CURVE", "MESH"}]
    print(f"[worker:scene] Objects after import: {imported}")
