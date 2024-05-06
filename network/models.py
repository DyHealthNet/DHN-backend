from dyhealthnet_project.myFunctions.calculate_association import calculate_score_from_nodes # test
from django.db import models

class Node(models.Model):
    description_text = models.CharField(max_length=200)
    cross_reference = models.CharField(max_length=200)

    def __str__(self):
        return self.description_text


class Edge(models.Model):
    node1 = models.ForeignKey(Node, on_delete=models.CASCADE, related_name='node1')
    node2 = models.ForeignKey(Node, on_delete=models.CASCADE, related_name='node2')
    score = models.DecimalField(max_digits=10, decimal_places=4)
    effect_size = models.DecimalField(max_digits=10, decimal_places=4)

    def __str__(self):
        return "Edge from " + self.node1.__str__() + " to " + self.node2.__str__()

    # Unused for now/ #TODO ?:
    def calculate_association_score(self):
        return calculate_score_from_nodes(self.node1, self.node2)
