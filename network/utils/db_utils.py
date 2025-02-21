from network.models import UserContextLink, Context
from django.db import connection

def get_context(user, context_value):
    if not user or not context_value:
        return None

    user_context = UserContextLink.objects.get(user_id=user.id,
                                               context_value=context_value)
    context = Context.objects.get(context_id=user_context.context_id)
    return context


def get_total_cohort_rows():
    # check all tables that contain "cohort" in the name
    # and return the total number of rows
    cursor = connection.cursor()
    cursor.execute("SELECT SUM(n_live_tup) FROM pg_stat_user_tables WHERE relname LIKE '%cohort%'")
    result = cursor.fetchone()[0]
    if not result:
        return 0
    return result
