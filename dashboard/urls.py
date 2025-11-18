from django.urls import path
from . import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.dashboard_home, name='home'),
    path('sites/', views.site_list, name='site-list'),
    path('sites/<uuid:site_id>/', views.site_detail, name='site-detail'),
    path('contacts/', views.contact_list, name='contact-list'),
    path('contacts/<uuid:contact_id>/', views.contact_detail, name='contact-detail'),
    path('visitors/<uuid:visitor_id>/', views.visitor_detail, name='visitor-detail'),
    path('demo/', views.demo_page, name='demo'),
]
