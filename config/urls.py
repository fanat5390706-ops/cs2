from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("web.api_urls")),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("web.urls")),
]
