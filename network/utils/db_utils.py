from network.models import UserContextLink, Context, Nodes

def get_context(user, context_value):
    if not user or not context_value:
        return None

    try:
        user_context = UserContextLink.objects.get(user_id=user.id,
                                                   context_value=context_value)
        return Context.objects.get(context_id=user_context.context_id)
    except (UserContextLink.DoesNotExist, Context.DoesNotExist):
        return None


def get_total_node_rows():
    return Nodes.objects.count()
