from django.conf import settings
from django.urls import reverse


def product_identity(request):
    return {
        "product_name": settings.PRODUCT_NAME,
        "product_version": settings.PRODUCT_VERSION,
        "product_description": settings.PRODUCT_DESCRIPTION,
        "capture_url": reverse("research:material_new"),
    }
