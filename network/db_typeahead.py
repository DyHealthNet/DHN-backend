import os
import django
from django.db.models import Q
from django.apps import apps
from django.db import connection
import timeit
import json
from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dyhealthnet_project.settings')
django.setup()

def query_description(query):
    model = apps.get_model('network', 'ViewDescriptionFTS')
    return model.objects.filter(description__search=query).values()

def query_display(query):
    model = apps.get_model('network', 'ViewDescriptionFTS')
    return model.objects.filter(display_name__icontains=query).values()

if __name__ == '__main__':
    start = timeit.default_timer()
    descriptions = query_description('low body')
    display_names = query_display('brca')
    print(f"Took {timeit.default_timer() - start:.2f} seconds.")

    print('Descriptions:')
    print(descriptions)

    print('Display names:')
    print(display_names)