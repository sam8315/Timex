from web.app import app


def _iter_api_routes(routes):
    """Flatten FastAPI 0.141+_IncludedRouter nests for path assertions."""
    for route in routes:
        path = getattr(route, "path", None)
        endpoint = getattr(route, "endpoint", None)
        if path is not None and endpoint is not None:
            yield route
        original = getattr(route, "original_router", None)
        if original is not None:
            yield from _iter_api_routes(original.routes)
        nested = getattr(route, "routes", None)
        if nested is not None:
            yield from _iter_api_routes(nested)


def test_admin_travel_preview_route_uses_policy_aware_endpoint():
    path = "/admin/leave-requests/travel-preview"
    routes = [
        route
        for route in _iter_api_routes(app.routes)
        if getattr(route, "path", None) == path
    ]

    assert len(routes) == 1
    assert routes[0].endpoint.__module__ == "web.routes.admin_travel_leave_preview"
    assert routes[0].endpoint.__name__ == "admin_travel_leave_preview"
