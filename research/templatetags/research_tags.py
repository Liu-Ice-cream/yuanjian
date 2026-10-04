from django import template
from django.conf import settings

register = template.Library()


@register.filter
def product_title(value):
    return str(value).replace("Linkding", settings.PRODUCT_NAME)
