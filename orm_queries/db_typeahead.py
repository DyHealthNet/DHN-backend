import os
import django
from django.db.models import Q
from django.apps import apps
import timeit

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dyhealthnet_project.settings')
django.setup()

def typeahead_query(query):
    model = apps.get_model('network', 'ViewDescriptionFTS')
    return model.objects.filter(Q(description__icontains=query) |
                                Q(display_name__icontains=query) |
                                Q(id__icontains=query)).values()

if __name__ == '__main__':
    start = timeit.default_timer()
    results = typeahead_query('high')
    print(f"Took {timeit.default_timer() - start} seconds.")

    print('Results:')
    for entry in results:
        print(entry)