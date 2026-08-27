from apps.audit.models import AuditLog


def get_client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def log_action(request, action, instance=None, description="", previous_value=None, new_value=None, reason=""):
    actor = getattr(request, "user", None)
    if not getattr(actor, "is_authenticated", False):
        actor = None
    return AuditLog.objects.create(
        actor=actor,
        action=action,
        affected_model=type(instance).__name__ if instance else "",
        affected_object_id=getattr(instance, "id", None),
        description=description[:255],
        previous_value=previous_value,
        new_value=new_value,
        reason=reason or "",
        ip_address=get_client_ip(request) if request else None,
    )
