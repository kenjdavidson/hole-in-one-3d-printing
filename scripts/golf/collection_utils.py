"""Collection helpers for generated golf plaque output."""

import bpy

from .config import CUTTERS_COLLECTION_NAME, OUTPUT_COLLECTION_NAME


def ensure_output_collection():
    """Return the root-level collection that holds generated plaque objects."""
    collection = bpy.data.collections.get(OUTPUT_COLLECTION_NAME)
    if collection is None:
        collection = bpy.data.collections.new(OUTPUT_COLLECTION_NAME)

    root = bpy.context.scene.collection
    if collection.name not in root.children:
        root.children.link(collection)

    return collection


def ensure_cutters_collection():
    """Return the root-level collection that holds generated cutter objects."""
    collection = bpy.data.collections.get(CUTTERS_COLLECTION_NAME)
    if collection is None:
        collection = bpy.data.collections.new(CUTTERS_COLLECTION_NAME)

    root = bpy.context.scene.collection
    if collection.name not in root.children:
        root.children.link(collection)

    return collection


def clear_collection(collection):
    """Remove all objects from a generated output collection."""
    for obj in list(collection.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def move_object_to_collection(obj, target_collection):
    """Link *obj* to *target_collection* and unlink it from all other collections."""
    for collection in list(obj.users_collection):
        collection.objects.unlink(obj)
    target_collection.objects.link(obj)