"""Task-local export stage; the shared Lightspeed service is never mutated."""
from contextvars import ContextVar

defer_images = ContextVar('lightspeed_defer_images', default=False)
