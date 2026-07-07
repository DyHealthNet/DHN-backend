from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.contrib.auth.models import User
from django.apps import apps

# Other nodes correspond to external data
class Disorder(models.Model):
    mondo_id = models.CharField(primary_key=True, max_length=200, db_index=True)
    display_name = models.CharField(max_length=200, blank=True, null=True)
    description = models.CharField(max_length=200, blank=True, null=True)
    xrefs = ArrayField(
        models.CharField(max_length=50, blank=True, null=True),
    )
    observation_source = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'disorder'


class Gene(models.Model):
    entrez_id = models.CharField(primary_key=True, max_length=200, db_index=True)
    display_name = models.CharField(max_length=200, blank=True, null=True)
    description = models.CharField(max_length=200, blank=True, null=True)
    synonyms = ArrayField(
        models.CharField(max_length=50, blank=True, null=True),
    )
    chromosome = models.CharField(max_length=200, blank=True, null=True)
    observation_source = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'gene'


class GenomicVariant(models.Model):
    clinvar_id = models.CharField(primary_key=True, max_length=200, db_index=True)
    alternative_sequence = models.CharField(max_length=200, blank=True, null=True)
    chromosome = models.CharField(max_length=200, blank=True, null=True)
    data_sources = models.CharField(max_length=200, blank=True, null=True)
    xrefs = ArrayField(
        models.CharField(max_length=50, blank=True, null=True),
    )
    position = models.CharField(max_length=200, blank=True, null=True)
    reference_sequence = models.CharField(max_length=200, blank=True, null=True)
    type = models.CharField(max_length=200, blank=True, null=True)
    variant_type = models.CharField(max_length=200, blank=True, null=True)
    observation_source = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'genomic_variant'


class Metabolite(models.Model):
    hmdb_id = models.CharField(primary_key=True, max_length=200, db_index=True)
    display_name = models.CharField(max_length=200, blank=True, null=True)
    description = models.CharField(max_length=200, blank=True, null=True)
    synonyms = models.CharField(max_length=200, blank=True, null=True)
    xrefs = ArrayField(
        models.CharField(max_length=50, blank=True, null=True),
    )
    observation_source = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'metabolite'


class Phenotype(models.Model):
    hpo_id = models.CharField(primary_key=True, max_length=200, db_index=True)
    display_name = models.CharField(max_length=200, blank=True, null=True)
    description = models.CharField(max_length=200, blank=True, null=True)
    xrefs = ArrayField(
        models.CharField(max_length=50, blank=True, null=True),
    )
    synonyms = models.CharField(max_length=200, blank=True, null=True)
    observation_source = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'phenotype'


class Protein(models.Model):
    uniprot_id = models.CharField(primary_key=True, max_length=200, db_index=True)
    display_name = models.CharField(max_length=200, blank=True, null=True)
    sequence = models.CharField(max_length=200, blank=True, null=True)
    description = models.CharField(max_length=200, blank=True, null=True)
    observation_source = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'protein'


# add model for all contexts so we can keep track of them
class Context(models.Model):
    context_id = models.IntegerField(primary_key=True, db_column='context_id')
    created_at = models.DateTimeField(auto_now_add=True)
    last_accessed = models.DateTimeField(blank=True, null=True)
    params = models.JSONField(blank=True, null=True)

    class Meta:
        managed = True
        db_table = 'context'


# Views combining several tables
class ViewDescriptionFTS(models.Model):
    id = models.CharField(primary_key=True, max_length=200, db_column='id')
    description = models.CharField(blank=True, null=True, db_column='description', max_length=200)
    display_name = models.CharField(blank=True, null=True, db_column='display_name', max_length=200)
    source_table = models.TextField(blank=True, null=True, db_column='source_table')
    xrefs = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'view_description_fts'


class ViewAssociationsEdges(models.Model):
    source_id = models.CharField(primary_key=True, blank=True, max_length=200, db_column='source_id', db_index=True)
    target_id = models.CharField(blank=True, null=True, max_length=200, db_column='target_id', db_index=True)

    class Meta:
        managed = False
        db_table = 'view_associations_edges'


class ViewReferencesEdges(models.Model):
    source_table = models.TextField(blank=True, null=True)
    cohort_id = models.CharField(primary_key=True, blank=True, max_length=200, db_column='cohort_id')
    reference_id = models.CharField(blank=True, null=True, max_length=200, db_column='reference_id')

    class Meta:
        managed = False
        db_table = 'view_references_edges'


class ViewExternalNodes(models.Model):
    node_id = models.CharField(primary_key=True, blank=True, max_length=200, db_column='node_id')
    source_table = models.TextField(blank=True, null=True, db_column='source_table')

    class Meta:
        managed = False
        db_table = 'view_external_nodes'


# New-style tables: single nodes table + parametric/nonparametric edge tables
class Nodes(models.Model):
    node_id = models.CharField(primary_key=True, max_length=200, db_column='node_id')
    display_name = models.CharField(max_length=200, blank=True, null=True)
    data_type = models.CharField(max_length=200, blank=True, null=True)
    node_group = models.CharField(max_length=200, blank=True, null=True)
    description = models.CharField(max_length=200, blank=True, null=True)
    xrefs = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'nodes'


class EdgesParametric(models.Model):
    id = models.IntegerField(primary_key=True, db_index=True)
    node_id_1 = models.ForeignKey(Nodes, models.DO_NOTHING, db_column='node_id_1',
                                   related_name='edges_parametric_node_1')
    node_id_2 = models.ForeignKey(Nodes, models.DO_NOTHING, db_column='node_id_2',
                                   related_name='edges_parametric_node_2')
    p_value = models.FloatField(blank=True, null=True)
    effect_size = models.FloatField(blank=True, null=True)
    test_type = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'edges_parametric'


class EdgesNonparametric(models.Model):
    id = models.IntegerField(primary_key=True, db_index=True)
    node_id_1 = models.ForeignKey(Nodes, models.DO_NOTHING, db_column='node_id_1',
                                   related_name='edges_nonparametric_node_1')
    node_id_2 = models.ForeignKey(Nodes, models.DO_NOTHING, db_column='node_id_2',
                                   related_name='edges_nonparametric_node_2')
    p_value = models.FloatField(blank=True, null=True)
    effect_size = models.FloatField(blank=True, null=True)
    test_type = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'edges_nonparametric'


class UserContextLink(models.Model):
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("FINISHED", "Finished"),
    ]
    user = models.ForeignKey(User, blank=True, null=True, on_delete=models.CASCADE)
    context = models.ForeignKey(Context,  blank=True, null=True, on_delete=models.CASCADE)
    #context_id = models.CharField(blank=True, max_length=200, db_column='context_id')
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    context_value = models.IntegerField(blank=True, null=True)
    context_task_id = models.CharField(blank=True, max_length=200)
    context_status = models.CharField(blank=True, max_length=200, choices=STATUS_CHOICES, default="Pending")

    class Meta:
        managed = True
        db_table = 'user_context'


class EdgesContextBase(models.Model):
    """Abstract base for per-context edge tables (edges_parametric_{id} / edges_nonparametric_{id}).
    Uses CharField instead of ForeignKey to avoid related_name clashes across dynamic subclasses."""
    node_id_1 = models.CharField(max_length=200, db_column='node_id_1')
    node_id_2 = models.CharField(max_length=200, db_column='node_id_2')
    p_value = models.FloatField(blank=True, null=True)
    effect_size = models.FloatField(blank=True, null=True)
    test_type = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        abstract = True


def create_dynamic_model(base_model, table_name): #registry
    """
    Create a dynamic model based on the specified base model and table name.
    :param base_model: The base model class to inherit from.
    :param table_name: The name of the database table.
    :return: A dynamically created model.
    """

    class DynamicModel(base_model):
        class Meta:
            db_table = table_name
            managed = False


    return DynamicModel
