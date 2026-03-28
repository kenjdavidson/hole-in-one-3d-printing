"""Element-processing strategies for the golf plaque generator.

The strategy pattern decouples *what kind of 3-D effect* a layer produces
from the core plaque-building loop.  Each :class:`ElementStrategy` subclass
knows only about its own geometry operations; :mod:`plaque_builder` stays free
of per-type conditional logic.

Adding a new effect (e.g. ``RELIEF``) requires:

1. Adding the new variant to :class:`~config.ElementType`.
2. Subclassing :class:`ElementStrategy` and implementing :meth:`process`.
3. Registering the instance in :data:`_STRATEGY_REGISTRY`.

No other module needs to change.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

import bpy

from .config import ElementType
from .cutter_pipeline import (
    CUTTER_TOP_POKE_MM,
    apply_boolean_cut,
    apply_solidify_if_present,
    duplicate_cutter,
    is_oversized_cutter,
    is_valid_cutter_mesh,
    log_oversized_cutter,
    postprocess_cutter_geometry,
    prepare_active_cutters,
    resolve_effective_depth,
)


@dataclass
class BuildContext:
    """Shared state passed to every strategy call during a single plaque build.

    Attributes:
        base:               The Blender base-plaque mesh object.
        plaque_thickness:   Overall plaque thickness in mm.
        base_x:             Plaque width in mm (after scaling).
        base_y:             Plaque height in mm (after scaling).
        output_collection:  Collection for final visible plaque objects.
        cutters_collection: Collection for hidden boolean-cutter objects.
    """

    base: object
    plaque_thickness: float
    base_x: float
    base_y: float
    output_collection: object
    cutters_collection: object

    @property
    def max_cutter_x(self) -> float:
        """Maximum allowed cutter width before the cutter is skipped."""
        return self.base_x * 3.0

    @property
    def max_cutter_y(self) -> float:
        """Maximum allowed cutter height before the cutter is skipped."""
        return self.base_y * 3.0


class ElementStrategy(ABC):
    """Abstract base: defines how a set of SVG outlines becomes 3-D geometry.

    Subclasses must implement :meth:`process`.  They should be stateless so
    that the singleton instances in :data:`_STRATEGY_REGISTRY` are safe to
    reuse across builds.
    """

    @abstractmethod
    def process(self, cutters, prefix, config, props, ctx: BuildContext, material):
        """Turn *cutters* into plaque geometry.

        Args:
            cutters:  SVG-derived mesh objects matching the layer prefix.
            prefix:   Layer name prefix, e.g. ``"Water"``.
            config:   :class:`~config.LayerConfig` for this prefix.
            props:    Blender scene property group (or :class:`~plaque_request.PlaqueRequest`).
            ctx:      Shared :class:`BuildContext` for the current build.
            material: Blender material to assign to the generated geometry.
        """


class CarveStrategy(ElementStrategy):
    """Cut the element into the plaque using Boolean difference operations.

    This is the full terrain carving pipeline: supports top-taper draft angles,
    stepped terraced walls, floor displacement textures, and automatic fallback
    cutters when a primary taper cut fails validation.
    """

    def process(self, cutters, prefix, config, props, ctx: BuildContext, material):
        for cutter in cutters:
            effective_depth = resolve_effective_depth(
                props, prefix, config.depth, ctx.plaque_thickness
            )
            cutter.location.z = ctx.plaque_thickness / 2 + CUTTER_TOP_POKE_MM

            active_cutters, use_top_taper, use_stepped_walls = prepare_active_cutters(
                cutter, props, effective_depth
            )

            for active_cutter in active_cutters:
                fallback_cutter = None
                if use_top_taper and not use_stepped_walls:
                    fallback_cutter = duplicate_cutter(active_cutter)

                postprocess_cutter_geometry(
                    active_cutter,
                    prefix,
                    props,
                    effective_depth,
                    ctx.plaque_thickness,
                    use_top_taper,
                    use_stepped_walls,
                )

                if not active_cutter.data.materials:
                    active_cutter.data.materials.append(material)

                if not is_valid_cutter_mesh(active_cutter):
                    continue

                if is_oversized_cutter(active_cutter, ctx.max_cutter_x, ctx.max_cutter_y):
                    log_oversized_cutter(active_cutter, ctx.max_cutter_x, ctx.max_cutter_y)
                    continue

                cut_applied = apply_boolean_cut(
                    ctx.base, active_cutter,
                    ctx.base_x, ctx.base_y, ctx.plaque_thickness,
                )

                active_cutter.display_type = "WIRE"
                active_cutter.hide_render = True

                if not cut_applied and fallback_cutter is not None:
                    fallback_cutter.location = active_cutter.location.copy()
                    apply_solidify_if_present(fallback_cutter)

                    if not fallback_cutter.data.materials:
                        fallback_cutter.data.materials.append(material)

                    if is_valid_cutter_mesh(fallback_cutter) and not is_oversized_cutter(
                        fallback_cutter, ctx.max_cutter_x, ctx.max_cutter_y
                    ):
                        apply_boolean_cut(
                            ctx.base, fallback_cutter,
                            ctx.base_x, ctx.base_y, ctx.plaque_thickness,
                        )

                    fallback_cutter.display_type = "WIRE"
                    fallback_cutter.hide_render = True


class EmbossStrategy(ElementStrategy):
    """Raise the element above the plaque surface via Solidify extrusion.

    The extrusion height is read from ``props.text_extrusion_height`` when
    present; otherwise ``config.depth`` is used as the default height.
    """

    def process(self, cutters, prefix, config, props, ctx: BuildContext, material):
        from .text_extrusion import extrude_text_objects

        extrude_text_objects(
            cutters,
            ctx.plaque_thickness,
            getattr(props, "text_extrusion_height", config.depth),
            material,
            ctx.output_collection,
        )


class EngraveStrategy(ElementStrategy):
    """Cut the element shallowly into the plaque surface with centred positioning.

    Unlike :class:`CarveStrategy`, the cutter is centred on the plaque surface
    rather than plunged from the top.  This avoids winding-order artefacts when
    cutting fine detail such as text outlines.

    The engrave depth is read from ``props.text_extrusion_height`` when present;
    otherwise ``config.depth`` is used.
    """

    def process(self, cutters, prefix, config, props, ctx: BuildContext, material):
        from .text_extrusion import engrave_text_objects

        engrave_text_objects(
            cutters,
            ctx.base,
            ctx.plaque_thickness,
            getattr(props, "text_extrusion_height", config.depth),
            material,
            ctx.cutters_collection,
        )


# ---------------------------------------------------------------------------
# Registry and factory
# ---------------------------------------------------------------------------

_STRATEGY_REGISTRY: "dict[ElementType, ElementStrategy]" = {
    ElementType.CARVE:   CarveStrategy(),
    ElementType.EMBOSS:  EmbossStrategy(),
    ElementType.ENGRAVE: EngraveStrategy(),
}


def get_strategy(element_type: ElementType) -> ElementStrategy:
    """Return the singleton strategy for *element_type*.

    Args:
        element_type: The :class:`~config.ElementType` variant to look up.

    Returns:
        The registered :class:`ElementStrategy` instance.

    Raises:
        KeyError: If no strategy is registered for *element_type*.
    """
    return _STRATEGY_REGISTRY[element_type]
