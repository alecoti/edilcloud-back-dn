from django.test import Client, override_settings

from edilcloud.settings.local import CORS_ALLOW_HEADERS


@override_settings(
    CORS_ALLOWED_ORIGINS=["http://localhost:35033", "http://127.0.0.1:35033"],
    CORS_ALLOW_HEADERS=CORS_ALLOW_HEADERS,
    CORS_ALLOW_ALL_ORIGINS=False,
)
def test_flutter_auth_and_localized_mutation_preflight():
    for origin in ("http://localhost:35033", "http://127.0.0.1:35033"):
        response = Client().options(
            "/api/v1/auth/access-code/request",
            HTTP_ORIGIN=origin,
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS=(
                "content-type,authorization,x-edilcloud-locale,x-edilcloud-client-mutation-id"
            ),
        )
        assert response.status_code == 200
        assert response["Access-Control-Allow-Origin"] == origin
        allowed = {header.strip() for header in response["Access-Control-Allow-Headers"].split(",")}
        assert {
            "content-type", "authorization", "x-edilcloud-locale",
            "x-edilcloud-client-mutation-id",
        } <= allowed


@override_settings(
    CORS_ALLOWED_ORIGINS=["http://localhost:35033"],
    CORS_ALLOW_ALL_ORIGINS=False,
)
def test_flutter_cors_does_not_allow_unknown_origins():
    for origin in ("https://unknown.example", "http://localhost:35033.evil.example"):
        response = Client().options(
            "/api/v1/auth/access-code/request",
            HTTP_ORIGIN=origin,
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        )
        assert "Access-Control-Allow-Origin" not in response
