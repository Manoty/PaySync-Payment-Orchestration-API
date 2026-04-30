from rest_framework.response import Response
from rest_framework import status as http_status


def success_response(data, message="Success", status=http_status.HTTP_200_OK):
    """
    Standardized success envelope.
    All PaySync responses follow the same shape — consumers
    can write predictable parsing logic.
    """
    return Response({
        "success": True,
        "message": message,
        "data": data,
    }, status=status)


def error_response(message, errors=None, status=http_status.HTTP_400_BAD_REQUEST):
    """
    Standardized error envelope.
    `errors` carries field-level validation details when relevant.
    """
    payload = {
        "success": False,
        "message": message,
    }
    if errors:
        payload["errors"] = errors
    return Response(payload, status=status)