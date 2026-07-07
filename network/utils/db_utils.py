from network.models import UserContextLink, Context, Nodes

def get_context(user, context_value):
    if not user or not context_value:
        return None

    user_context = UserContextLink.objects.get(user_id=user.id,
                                               context_value=context_value)
    context = Context.objects.get(context_id=user_context.context_id)
    return context


def get_total_node_rows():
    return Nodes.objects.count()
