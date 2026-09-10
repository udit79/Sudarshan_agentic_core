"""API package initialization.

The FastAPI app is exported lazily so infrastructure modules such as the
durable scheduler can be imported without recursively importing ``api.server``.
"""

__all__ = ["app"]


def __getattr__(name: str):
    if name == "app":
        from api.server import app

        return app
    raise AttributeError(name)
