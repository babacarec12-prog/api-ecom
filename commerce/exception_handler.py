"""Uniformise aussi les erreurs générées directement par Django REST Framework."""
from rest_framework.views import exception_handler


def json_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return None

    detail = response.data.get("detail") if isinstance(response.data, dict) else None
    if detail:
        message = str(detail)
    elif isinstance(response.data, dict):
        message = "; ".join(
            f"{field} : {value}" for field, value in response.data.items()
        )
    else:
        message = str(response.data)
    response.data = {"success": False, "error": message, "data": {}}
    return response
