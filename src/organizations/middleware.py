SESSION_KEY = "organization_id"


def active_memberships(user):
    return user.memberships.select_related("organization").filter(organization__is_active=True)


class CurrentOrganizationMiddleware:
    """Define request.organization y request.membership (la organización activa).

    La organización elegida se guarda en la sesión; si no hay una válida se usa
    la primera del usuario. Va después de AuthenticationMiddleware.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.organization = request.membership = None
        if request.user.is_authenticated:
            memberships = active_memberships(request.user)
            selected = request.session.get(SESSION_KEY)
            membership = memberships.filter(organization_id=selected).first() if selected else None
            if membership is None:
                membership = memberships.order_by("organization__name").first()
            if membership is not None:
                request.membership = membership
                request.organization = membership.organization
                if selected != membership.organization_id:
                    request.session[SESSION_KEY] = membership.organization_id
        return self.get_response(request)
