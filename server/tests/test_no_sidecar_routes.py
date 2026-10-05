from server.main import create_app


def test_application_exposes_no_sidecar_routes():
    paths = {route.path for route in create_app().routes}

    assert not any(path.startswith("/api/sidecar") for path in paths)
