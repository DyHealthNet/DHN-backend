from django.contrib.auth.models import User, Group
from rest_framework import serializers

from .models import Node, Edge

from .models import Node
class UserSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = User
        fields = ['url', 'username', 'email', 'groups']
class GroupSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Group
        fields = ['url', 'name']

class EdgeSerializer(serializers.HyperlinkedModelSerializer):
    node1 = serializers.HyperlinkedRelatedField(
        many=False,
        read_only=True,
        view_name='node1-detail'
    )
    node2 = serializers.HyperlinkedRelatedField(
        many=False,
        read_only=True,
        view_name='node2-detail'
    )

    class Meta:
        model = Edge
        fields = ['node1', 'node2', 'score', 'effect_size']


class VariablesSerializer(serializers.Serializer):
   """Your data serializer, define your fields here."""
   variables = serializers.DictField()
# Returns all possible phenotyp variables grouped by their type in JSON format
# e.g. {"discrete":["age"], "countinous":["BMI","Height"]}
# class GetVariablesSerializer(serializers.Serializer):
#     id = serializers.IntegerField(read_only=True)
#     title = serializers.CharField(required=False, allow_blank=True, max_length=100)
#     code = serializers.CharField(style={'base_template': 'textarea.html'})
#     linenos = serializers.BooleanField(required=False)
#     language = serializers.ChoiceField(choices=LANGUAGE_CHOICES, default='python')
#     style = serializers.ChoiceField(choices=STYLE_CHOICES, default='friendly')
#
#     def create(self, validated_data):
#         """
#         Create and return a new `Snippet` instance, given the validated data.
#         """
#         return Snippet.objects.create(**validated_data)
#
#     def update(self, instance, validated_data):
#         """
#         Update and return an existing `Snippet` instance, given the validated data.
#         """
#         instance.title = validated_data.get('title', instance.title)
#         instance.code = validated_data.get('code', instance.code)
#         instance.linenos = validated_data.get('linenos', instance.linenos)
#         instance.language = validated_data.get('language', instance.language)
#         instance.style = validated_data.get('style', instance.style)
#         instance.save()
#         return instance
