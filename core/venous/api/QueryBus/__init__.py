# WP-15: re-export the formal port from core/venous/_ports/. Legacy import path stays valid.
from core.venous._ports.api.QueryBus import QueryBusProtocol  # noqa: F401
from core.venous.api.QueryBus.QueryBus import QueryBus  # noqa: F401
