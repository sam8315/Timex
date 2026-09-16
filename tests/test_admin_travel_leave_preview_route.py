from web.app import app


def test_admin_travel_preview_route_uses_policy_aware_endpoint():
    path = "/admin/leave-requests/travel-preview"
    routes = [route for route in app.routes if getattr(route, "path", None) == path]

    assert len(routes) == 1
    assert routes[0].endpoint.__module__ == "web.routes.admin_travel_leave_preview"
    assert routes[0].endpoint.__name__ == "admin_travel_leave_preview"
