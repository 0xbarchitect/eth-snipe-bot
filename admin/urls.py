from django.urls import path, include
from django.contrib import admin
from console.admin import admin_site

urlpatterns = [    
    path('admin/', admin_site.urls),
]