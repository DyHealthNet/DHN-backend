import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dyhealthnet_project.settings')

app = Celery('dhn')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
