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
    pval = models.DecimalField(max_digits=10, decimal_places=4)
    pval_adj = models.DecimalField(max_digits=10, decimal_places=4)
    effect_size = models.DecimalField(max_digits=10, decimal_places=4)
    effect_size_type = models.CharField(max_length=25)

    def __str__(self):
        return "Edge from " + self.node1.__str__() + " to " + self.node2.__str__()

    def passed_pvalue_threshold(self, threshold):
        if self.pval_adj < threshold:
            return True
        else:
            return False

    #TODO:
    def calculate_association_score(self):
        return calculate_score_from_nodes(self.node1, self.node2)

## Automatically generated models for the tables of the actual db from the database group via command
## python manage.py inspectdb > network/models.py

# class AuthGroup(models.Model):
#     name = models.CharField(unique=True, max_length=150)
#
#     class Meta:
#         managed = False
#         db_table = 'auth_group'
#
#
# class AuthGroupPermissions(models.Model):
#     id = models.BigAutoField(primary_key=True)
#     group = models.ForeignKey(AuthGroup, models.DO_NOTHING)
#     permission = models.ForeignKey('AuthPermission', models.DO_NOTHING)
#
#     class Meta:
#         managed = False
#         db_table = 'auth_group_permissions'
#         unique_together = (('group', 'permission'),)
#
#
# class AuthPermission(models.Model):
#     name = models.CharField(max_length=255)
#     content_type = models.ForeignKey('DjangoContentType', models.DO_NOTHING)
#     codename = models.CharField(max_length=100)
#
#     class Meta:
#         managed = False
#         db_table = 'auth_permission'
#         unique_together = (('content_type', 'codename'),)
#
#
# class AuthUser(models.Model):
#     password = models.CharField(max_length=128)
#     last_login = models.DateTimeField(blank=True, null=True)
#     is_superuser = models.BooleanField()
#     username = models.CharField(unique=True, max_length=150)
#     first_name = models.CharField(max_length=150)
#     last_name = models.CharField(max_length=150)
#     email = models.CharField(max_length=254)
#     is_staff = models.BooleanField()
#     is_active = models.BooleanField()
#     date_joined = models.DateTimeField()
#
#     class Meta:
#         managed = False
#         db_table = 'auth_user'
#
#
# class AuthUserGroups(models.Model):
#     id = models.BigAutoField(primary_key=True)
#     user = models.ForeignKey(AuthUser, models.DO_NOTHING)
#     group = models.ForeignKey(AuthGroup, models.DO_NOTHING)
#
#     class Meta:
#         managed = False
#         db_table = 'auth_user_groups'
#         unique_together = (('user', 'group'),)
#
#
# class AuthUserUserPermissions(models.Model):
#     id = models.BigAutoField(primary_key=True)
#     user = models.ForeignKey(AuthUser, models.DO_NOTHING)
#     permission = models.ForeignKey(AuthPermission, models.DO_NOTHING)
#
#     class Meta:
#         managed = False
#         db_table = 'auth_user_user_permissions'
#         unique_together = (('user', 'permission'),)


class DisorderAssociatesPhenotypes(models.Model):
    mondo = models.ForeignKey('Disorders', models.DO_NOTHING, blank=True, null=True)
    hpo = models.ForeignKey('Phenotypes', models.DO_NOTHING, blank=True, null=True)
    edge_source = models.CharField(blank=True, null=True, max_length=200)

    class Meta:
        managed = False
        db_table = 'disorder_associates_phenotypes'


class Disorders(models.Model):
    mondo_id = models.CharField(primary_key=True, max_length=200)
    description = models.CharField(blank=True, null=True, max_length=200)
    xrefs = models.TextField(blank=True, null=True)  # This field type is a guess.
    observation_source = models.CharField(blank=True, null=True, max_length=200)

    class Meta:
        managed = False
        db_table = 'disorders'


# class DjangoAdminLog(models.Model):
#     action_time = models.DateTimeField()
#     object_id = models.TextField(blank=True, null=True)
#     object_repr = models.CharField(max_length=200)
#     action_flag = models.SmallIntegerField()
#     change_message = models.TextField()
#     content_type = models.ForeignKey('DjangoContentType', models.DO_NOTHING, blank=True, null=True)
#     user = models.ForeignKey(AuthUser, models.DO_NOTHING)
#
#     class Meta:
#         managed = False
#         db_table = 'django_admin_log'
#
#
# class DjangoContentType(models.Model):
#     app_label = models.CharField(max_length=100)
#     model = models.CharField(max_length=100)
#
#     class Meta:
#         managed = False
#         db_table = 'django_content_type'
#         unique_together = (('app_label', 'model'),)
#
#
# class DjangoMigrations(models.Model):
#     id = models.BigAutoField(primary_key=True)
#     app = models.CharField(max_length=255)
#     name = models.CharField(max_length=255)
#     applied = models.DateTimeField()
#
#     class Meta:
#         managed = False
#         db_table = 'django_migrations'
#
#
# class DjangoSession(models.Model):
#     session_key = models.CharField(primary_key=True, max_length=40)
#     session_data = models.TextField()
#     expire_date = models.DateTimeField()
#
#     class Meta:
#         managed = False
#         db_table = 'django_session'


class EffectsDisorderDisorder(models.Model):
    mondo_id_1 = models.ForeignKey(Disorders, models.DO_NOTHING, db_column='mondo_id_1', blank=True, null=True)
    mondo_id_2 = models.ForeignKey(Disorders, models.DO_NOTHING, db_column='mondo_id_2', related_name='effectsdisorderdisorder_mondo_id_2_set', blank=True, null=True)
    p_value = models.FloatField(blank=True, null=True)
    adjusted_p_value = models.FloatField(blank=True, null=True)
    effect_size = models.FloatField(blank=True, null=True)
    effect_size_type = models.CharField(blank=True, null=True, max_length=200)

    class Meta:
        managed = False
        db_table = 'effects_disorder_disorder'


class EffectsMetaboliteDisorder(models.Model):
    hmdb = models.ForeignKey('Metabolites', models.DO_NOTHING, blank=True, null=True)
    mondo = models.ForeignKey(Disorders, models.DO_NOTHING, blank=True, null=True)
    p_value = models.FloatField(blank=True, null=True)
    adjusted_p_value = models.FloatField(blank=True, null=True)
    effect_size = models.FloatField(blank=True, null=True)
    effect_size_type = models.CharField(blank=True, null=True, max_length=200)

    class Meta:
        managed = False
        db_table = 'effects_metabolite_disorder'


class EffectsMetaboliteMetabolite(models.Model):
    hmdb_id_1 = models.ForeignKey('Metabolites', models.DO_NOTHING, db_column='hmdb_id_1', blank=True, null=True)
    hmdb_id_2 = models.ForeignKey('Metabolites', models.DO_NOTHING, db_column='hmdb_id_2', related_name='effectsmetabolitemetabolite_hmdb_id_2_set', blank=True, null=True)
    p_value = models.FloatField(blank=True, null=True)
    adjusted_p_value = models.FloatField(blank=True, null=True)
    effect_size = models.FloatField(blank=True, null=True)
    effect_size_type = models.CharField(blank=True, null=True, max_length=200)

    class Meta:
        managed = False
        db_table = 'effects_metabolite_metabolite'


class EffectsMetabolitePhenotype(models.Model):
    hmdb = models.ForeignKey('Metabolites', models.DO_NOTHING, blank=True, null=True)
    hpo = models.ForeignKey('Phenotypes', models.DO_NOTHING, blank=True, null=True)
    p_value = models.FloatField(blank=True, null=True)
    adjusted_p_value = models.FloatField(blank=True, null=True)
    effect_size = models.FloatField(blank=True, null=True)
    effect_size_type = models.CharField(blank=True, null=True, max_length=200)

    class Meta:
        managed = False
        db_table = 'effects_metabolite_phenotype'


class EffectsPhenotypeDisorder(models.Model):
    hpo = models.ForeignKey('Phenotypes', models.DO_NOTHING, blank=True, null=True)
    mondo = models.ForeignKey(Disorders, models.DO_NOTHING, blank=True, null=True)
    p_value = models.FloatField(blank=True, null=True)
    adjusted_p_value = models.FloatField(blank=True, null=True)
    effect_size = models.FloatField(blank=True, null=True)
    effect_size_type = models.CharField(blank=True, null=True, max_length=200)

    class Meta:
        managed = False
        db_table = 'effects_phenotype_disorder'


class EffectsPhenotypePhenotype(models.Model):
    hpo_id_1 = models.ForeignKey('Phenotypes', models.DO_NOTHING, db_column='hpo_id_1', blank=True, null=True)
    hpo_id_2 = models.ForeignKey('Phenotypes', models.DO_NOTHING, db_column='hpo_id_2', related_name='effectsphenotypephenotype_hpo_id_2_set', blank=True, null=True)
    p_value = models.FloatField(blank=True, null=True)
    adjusted_p_value = models.FloatField(blank=True, null=True)
    effect_size = models.FloatField(blank=True, null=True)
    effect_size_type = models.CharField(blank=True, null=True, max_length=200)

    class Meta:
        managed = False
        db_table = 'effects_phenotype_phenotype'


class EffectsProteinDisorder(models.Model):
    uniprot = models.ForeignKey('Proteins', models.DO_NOTHING, related_name='effectsproteindisorder_uniprot_set', blank=True, null=True)
    mondo = models.ForeignKey(Disorders, models.DO_NOTHING, blank=True, null=True)
    p_value = models.FloatField(blank=True, null=True)
    adjusted_p_value = models.FloatField(blank=True, null=True)
    effect_size = models.FloatField(blank=True, null=True)
    effect_size_type = models.CharField(blank=True, null=True, max_length=200)

    class Meta:
        managed = False
        db_table = 'effects_protein_disorder'


class EffectsProteinMetabolite(models.Model):
    uniprot = models.ForeignKey('Proteins', models.DO_NOTHING, blank=True, null=True)
    hmdb = models.ForeignKey('Metabolites', models.DO_NOTHING, blank=True, null=True)
    p_value = models.FloatField(blank=True, null=True)
    adjusted_p_value = models.FloatField(blank=True, null=True)
    effect_size = models.FloatField(blank=True, null=True)
    effect_size_type = models.CharField(blank=True, null=True, max_length=200)

    class Meta:
        managed = False
        db_table = 'effects_protein_metabolite'


class EffectsProteinPhenotype(models.Model):
    uniprot = models.ForeignKey('Proteins', models.DO_NOTHING, blank=True, null=True)
    hpo = models.ForeignKey('Phenotypes', models.DO_NOTHING, blank=True, null=True)
    p_value = models.FloatField(blank=True, null=True)
    adjusted_p_value = models.FloatField(blank=True, null=True)
    effect_size = models.FloatField(blank=True, null=True)
    effect_size_type = models.CharField(blank=True, null=True, max_length=200)

    class Meta:
        managed = False
        db_table = 'effects_protein_phenotype'


class EffectsProteinProtein(models.Model):
    uniprot_id_1 = models.ForeignKey('Proteins', models.DO_NOTHING, db_column='uniprot_id_1', related_name='effectsproteinprotein_uniprot_id_1_set', blank=True, null=True)
    uniprot_id_2 = models.ForeignKey('Proteins', models.DO_NOTHING, db_column='uniprot_id_2', related_name='effectsproteinprotein_uniprot_id_2_set',blank=True, null=True)
    p_value = models.FloatField(blank=True, null=True)
    adjusted_p_value = models.FloatField(blank=True, null=True)
    effect_size = models.FloatField(blank=True, null=True)
    effect_size_type = models.CharField(blank=True, null=True, max_length=200)

    class Meta:
        managed = False
        db_table = 'effects_protein_protein'


class GeneAssociatesDisorders(models.Model):
    entrez = models.ForeignKey('Genes', models.DO_NOTHING, blank=True, null=True)
    mondo = models.ForeignKey(Disorders, models.DO_NOTHING, blank=True, null=True)
    edge_source = models.CharField(blank=True, null=True, max_length=200)

    class Meta:
        managed = False
        db_table = 'gene_associates_disorders'


class Genes(models.Model):
    entrez_id = models.CharField(primary_key=True, max_length=200)
    display_name = models.CharField(blank=True, null=True, max_length=200)
    description = models.CharField(blank=True, null=True, max_length=200)
    synonyms = models.TextField(blank=True, null=True)  # This field type is a guess.
    chromosome = models.CharField(blank=True, null=True, max_length=200)
    observation_source = models.CharField(blank=True, null=True, max_length=200)

    class Meta:
        managed = False
        db_table = 'genes'


class MetaboliteAssociatesDisorders(models.Model):
    hmdb = models.ForeignKey('Metabolites', models.DO_NOTHING, blank=True, null=True)
    mondo = models.ForeignKey(Disorders, models.DO_NOTHING, blank=True, null=True)
    edge_source = models.CharField(blank=True, null=True, max_length=200)

    class Meta:
        managed = False
        db_table = 'metabolite_associates_disorders'


class Metabolites(models.Model):
    hmdb_id = models.CharField(primary_key=True, max_length=200)
    display_name = models.CharField(blank=True, null=True, max_length=200)
    description = models.CharField(blank=True, null=True, max_length=200)
    synonyms = models.CharField(blank=True, null=True, max_length=200)
    xrefs = models.TextField(blank=True, null=True)  # This field type is a guess.
    observation_source = models.CharField(blank=True, null=True, max_length=200)

    class Meta:
        managed = False
        db_table = 'metabolites'


class Phenotypes(models.Model):
    hpo_id = models.CharField(primary_key=True, max_length=200)
    display_name = models.CharField(blank=True, null=True, max_length=200)
    description = models.CharField(blank=True, null=True, max_length=200)
    xrefs = models.TextField(blank=True, null=True)  # This field type is a guess.
    synonyms = models.CharField(blank=True, null=True, max_length=200)
    observation_source = models.CharField(blank=True, null=True, max_length=200)

    class Meta:
        managed = False
        db_table = 'phenotypes'


class ProteinAssociatesMetabolites(models.Model):
    uniprot = models.ForeignKey('Proteins', models.DO_NOTHING, blank=True, null=True)
    hmdb = models.ForeignKey(Metabolites, models.DO_NOTHING, blank=True, null=True)
    edge_source = models.CharField(blank=True, null=True, max_length=200)

    class Meta:
        managed = False
        db_table = 'protein_associates_metabolites'


class ProteinAssociatesProteins(models.Model):
    uniprot_id_memberOne = models.ForeignKey('Proteins', models.DO_NOTHING, db_column='uniprot_id_memberOne',
                                             related_name='associates_member_one', blank=True, null=True)
    uniprot_id_memberTwo = models.ForeignKey('Proteins', models.DO_NOTHING, db_column='uniprot_id_memberTwo',
                                             related_name='associates_member_two', blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'protein_associates_proteins'


class Proteins(models.Model):
    uniprot_id = models.CharField(primary_key=True, max_length=200)
    sequence = models.CharField(blank=True, null=True, max_length=200)
    gene_entrez_id = models.CharField(blank=True, null=True, max_length=200)
    description = models.CharField(blank=True, null=True, max_length=200)
    observation_source = models.CharField(blank=True, null=True, max_length=200)

    class Meta:
        managed = False
        db_table = 'proteins'
