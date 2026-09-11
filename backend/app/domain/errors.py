class EngineNotImplementedError(Exception):
    """The fixture stub cannot calculate arbitrary orders."""


class BoxNotFoundError(Exception):
    pass


class BoxConflictError(Exception):
    pass
