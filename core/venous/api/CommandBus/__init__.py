# WP-15: re-export the formal port from core/venous/_ports/. Legacy import path stays valid.
from core.venous._ports.api.CommandBus import CommandBusProtocol  # noqa: F401
from core.venous.api.CommandBus.CommandBus import CommandBus  # noqa: F401
