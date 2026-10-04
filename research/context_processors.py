from django.conf import settings


def product_identity(request):
    return {
        "product_name": settings.PRODUCT_NAME,
        "product_version": settings.PRODUCT_VERSION,
        "product_description": settings.PRODUCT_DESCRIPTION,
    }
