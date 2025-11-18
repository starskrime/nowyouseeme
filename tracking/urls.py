from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'sites', views.SiteViewSet)
router.register(r'visitors', views.VisitorViewSet)
router.register(r'contacts', views.ContactViewSet)
router.register(r'events', views.EventViewSet)
router.register(r'conversion-goals', views.ConversionGoalViewSet)

urlpatterns = [
    path('track/', views.track_event, name='track-event'),
    path('', include(router.urls)),
]
