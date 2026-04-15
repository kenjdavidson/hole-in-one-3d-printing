"""Insert-mode pipeline runner.

Drives the ``build_inserts`` pipeline with an
:class:`~golf.insert_request.InsertRequest` built from the API-supplied
*params* dict.
"""


def run(params: dict) -> None:
    """Execute the colour-insert set pipeline.

    Args:
        params: Build parameters from the API (a ``model_dump()`` of
                :class:`~api.schemas.InsertSettings`).  Unknown keys are
                silently ignored so that the schema can evolve independently of
                the pipeline dataclass.
    """
    from golf.insert_builder import build_inserts    # noqa: PLC0415
    from golf.insert_request import InsertRequest    # noqa: PLC0415

    valid_fields = set(InsertRequest.__dataclass_fields__)
    filtered = {k: v for k, v in params.items() if k in valid_fields}
    req = InsertRequest(**filtered)

    print(f"[worker:insert] Running build_inserts with: {filtered}")
    build_inserts(req)
