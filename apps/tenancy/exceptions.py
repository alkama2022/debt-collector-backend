from rest_framework.views import exception_handler
from rest_framework.response import Response

def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is not None:
        # normalize to {success:false, message, errors, code}
        code = response.status_code
        data = response.data
        if isinstance(data, dict) and "success" not in data:
            message = data.get("detail") or data.get("message") or "Request failed"
            errors = {k: v for k, v in data.items() if k not in ("detail", "message")} if isinstance(data, dict) else {}
            if "detail" in data and not errors:
                errors = {}
                message = str(data["detail"])
            return Response({"success": False, "message": message, "errors": errors, "code": _code_for_status(code)}, status=code)
    return response

def _code_for_status(status):
    mapping = {400: "VALIDATION_ERROR", 401: "AUTH_REQUIRED", 403: "FORBIDDEN", 404: "NOT_FOUND", 429: "RATE_LIMITED", 409: "CONFLICT"}
    return mapping.get(status, "ERROR")
