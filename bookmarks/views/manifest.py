from django.conf import settings
from django.http import JsonResponse


def manifest(request):
    prefix = "/" + settings.LD_CONTEXT_PATH
    return JsonResponse(
        {
            "short_name": settings.PRODUCT_NAME,
            "name": settings.PRODUCT_NAME,
            "description": settings.PRODUCT_DESCRIPTION,
            "start_url": prefix + "research/",
            "display": "standalone",
            "scope": prefix,
            "theme_color": "#0f766e",
            "background_color": "#161822"
            if request.user_profile.theme == "dark"
            else "#ffffff",
            "icons": [
                {
                    "src": prefix + "static/yuanjian.svg",
                    "type": "image/svg+xml",
                    "sizes": "any",
                    "purpose": "any maskable",
                }
            ],
            "shortcuts": [
                {"name": "收集资料", "url": prefix + "research/materials/new"},
                {"name": "我的课题", "url": prefix + "research/projects"},
                {"name": "待阅读", "url": prefix + "research/?stage=collected"},
            ],
            "share_target": {
                "action": prefix + "research/materials/new",
                "method": "GET",
                "enctype": "application/x-www-form-urlencoded",
                "params": {"url": "url", "text": "text", "title": "title"},
            },
        }
    )
