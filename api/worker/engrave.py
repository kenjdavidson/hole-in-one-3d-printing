"""Engrave-mode pipeline runner.

Drives the ``carve_plaque`` pipeline with a :class:`~golf.plaque_request.PlaqueRequest`
built from the API-supplied *params* dict.
"""


def run(params: dict) -> None:
    """Execute the carved / engraved plaque pipeline.

    Args:
        params: Build parameters from the API (a ``model_dump()`` of
                :class:`~api.schemas.EngraveSettings`).  Unknown keys are
                silently ignored so that the schema can evolve independently of
                the pipeline dataclass.
    """
    from golf.plaque_builder import carve_plaque     # noqa: PLC0415
    from golf.plaque_request import PlaqueRequest    # noqa: PLC0415

    valid_fields = set(PlaqueRequest.__dataclass_fields__)
    filtered = {k: v for k, v in params.items() if k in valid_fields}
    req = PlaqueRequest(**filtered)

    print(f"[worker:engrave] Running carve_plaque with: {filtered}")
    carve_plaque(req)
