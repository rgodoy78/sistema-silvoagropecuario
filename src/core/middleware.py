from django.conf import settings


class PermissionsPolicyMiddleware:
    """Añade la cabecera Permissions-Policy (Django no la gestiona de forma nativa)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault("Permissions-Policy", settings.PERMISSIONS_POLICY)
        return response
