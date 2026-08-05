__all__ = ["ArtDesignGraph"]


def __getattr__(name: str):
    """Load the compiled graph lazily to keep schema imports dependency-safe."""
    if name == "ArtDesignGraph":
        from .art_design_graph import ArtDesignGraph

        globals()[name] = ArtDesignGraph
        return ArtDesignGraph
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
