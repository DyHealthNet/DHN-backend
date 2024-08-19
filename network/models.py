from django.db import models

# 'Cohort' models correspond to CHRIS nodes
class CohortMetabolite(models.Model):
    cohort_id = models.CharField(primary_key=True, max_length=200, db_index=True)
    display_name = models.CharField(max_length=200, blank=True, null=True)
    description = models.CharField(max_length=200, blank=True, null=True)
    xrefs = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'cohort_metabolite'

class CohortPhenotype(models.Model):
    cohort_id = models.CharField(primary_key=True, max_length=200, db_index=True)
    display_name = models.CharField(max_length=200, blank=True, null=True)
    description = models.CharField(max_length=200, blank=True, null=True)
    xrefs = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'cohort_phenotype'

class CohortProtein(models.Model):
    cohort_id = models.CharField(primary_key=True, max_length=200, db_index=True)
    display_name = models.CharField(max_length=200, blank=True, null=True)
    description = models.CharField(max_length=200, blank=True, null=True)
    xrefs = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'cohort_protein'


# Other nodes correspond to external data
class Disorder(models.Model):
    mondo_id = models.CharField(primary_key=True, max_length=200, db_index=True)
    description = models.CharField(max_length=200, blank=True, null=True)
    xrefs = models.TextField(blank=True, null=True)
    observation_source = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'disorder'

class Gene(models.Model):
    entrez_id = models.CharField(primary_key=True, max_length=200, db_index=True)
    display_name = models.CharField(max_length=200, blank=True, null=True)
    description = models.CharField(max_length=200, blank=True, null=True)
    synonyms = models.TextField(blank=True, null=True)
    chromosome = models.CharField(max_length=200, blank=True, null=True)
    observation_source = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'gene'

class GenomicVariant(models.Model):
    variant_primarydomainid = models.CharField(db_column='variant_primaryDomainId', primary_key=True, max_length=200, db_index=True)
    alternativesequence = models.CharField(db_column='alternativeSequence', max_length=200, blank=True, null=True)
    chromosome = models.CharField(max_length=200, blank=True, null=True)
    created = models.CharField(max_length=200, blank=True, null=True)
    datasources = models.CharField(db_column='dataSources', max_length=200, blank=True, null=True)
    domainids = models.CharField(db_column='domainIds', max_length=200, blank=True, null=True)
    position = models.CharField(max_length=200, blank=True, null=True)
    referencesequence = models.CharField(db_column='referenceSequence', max_length=200, blank=True, null=True)
    type = models.CharField(max_length=200, blank=True, null=True)
    varianttype = models.CharField(db_column='variantType', max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'genomic_variant'

class Metabolite(models.Model):
    hmdb_id = models.CharField(primary_key=True, max_length=200, db_index=True)
    display_name = models.CharField(max_length=200, blank=True, null=True)
    description = models.CharField(max_length=200, blank=True, null=True)
    synonyms = models.CharField(max_length=200, blank=True, null=True)
    xrefs = models.TextField(blank=True, null=True)
    observation_source = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'metabolite'

class Phenotype(models.Model):
    hpo_id = models.CharField(primary_key=True, max_length=200, db_index=True)
    display_name = models.CharField(max_length=200, blank=True, null=True)
    description = models.CharField(max_length=200, blank=True, null=True)
    xrefs = models.TextField(blank=True, null=True)
    synonyms = models.CharField(max_length=200, blank=True, null=True)
    observation_source = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'phenotype'

class Protein(models.Model):
    uniprot_id = models.CharField(primary_key=True, max_length=200, db_index=True)
    display_name = models.CharField(max_length=200, blank=True, null=True)
    sequence = models.CharField(max_length=200, blank=True, null=True)
    gene_entrez_id = models.CharField(max_length=200, blank=True, null=True)
    description = models.CharField(max_length=200, blank=True, null=True)
    observation_source = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'protein'


# 'Associates' models correspond to externally verified associations between nodes
class DisorderAssociatesPhenotype(models.Model):
    mondo_id = models.ForeignKey('Disorder', models.DO_NOTHING, blank=True, null=True)
    hpo_id = models.ForeignKey('Phenotype', models.DO_NOTHING, blank=True, null=True)
    edge_source = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'disorder_associates_phenotype'

class GeneAssociatesDisorder(models.Model):
    entrez_id = models.ForeignKey('Gene', models.DO_NOTHING, blank=True, null=True)
    mondo_id = models.ForeignKey('Disorder', models.DO_NOTHING, blank=True, null=True)
    edge_source = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'gene_associates_disorder'

class MetaboliteAssociatesDisorder(models.Model):
    hmdb_id = models.ForeignKey('Metabolite', models.DO_NOTHING, blank=True, null=True)
    mondo_id = models.ForeignKey('Disorder', models.DO_NOTHING, blank=True, null=True)
    edge_source = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'metabolite_associates_disorder'

class ProteinAssociatesMetabolite(models.Model):
    uniprot_id = models.ForeignKey('Protein', models.DO_NOTHING, blank=True, null=True)
    hmdb_id = models.ForeignKey('Metabolite', models.DO_NOTHING, blank=True, null=True)
    edge_source = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'protein_associates_metabolite'

class ProteinAssociatesProtein(models.Model):
    uniprot_id_1 = models.ForeignKey('Protein', models.DO_NOTHING, db_column='uniprot_id_1', blank=True, null=True,
                                     related_name='protein_1')
    uniprot_id_2 = models.ForeignKey('Protein', models.DO_NOTHING, db_column='uniprot_id_2', blank=True, null=True,
                                     related_name='protein_2')

    class Meta:
        managed = False
        db_table = 'protein_associates_protein'


# 'Effects' models correspond to edges between CHRIS nodes with calculated association scores
class EffectsMetaboliteMetabolite(models.Model):
    id = models.IntegerField(primary_key=True, db_index=True)
    metabolite_1 = models.ForeignKey('CohortMetabolite', models.DO_NOTHING, db_column='metabolite_id_1', blank=True, null=True,
                                        related_name='cohort_metabolite_1')
    metabolite_2 = models.ForeignKey('CohortMetabolite', models.DO_NOTHING, db_column='metabolite_id_2', blank=True, null=True,
                                        related_name='cohort_metabolite_2')
    p_value = models.FloatField(blank=True, null=True)
    adjusted_p_value = models.FloatField(blank=True, null=True)
    effect_size = models.FloatField(blank=True, null=True)
    effect_size_type = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'effects_metabolite_metabolite'

class EffectsMetabolitePhenotype(models.Model):
    id = models.IntegerField(primary_key=True, db_index=True)
    metabolite = models.ForeignKey('CohortMetabolite', models.DO_NOTHING, blank=True, null=True)
    phenotype = models.ForeignKey('CohortPhenotype', models.DO_NOTHING, blank=True, null=True)
    p_value = models.FloatField(blank=True, null=True)
    adjusted_p_value = models.FloatField(blank=True, null=True)
    effect_size = models.FloatField(blank=True, null=True)
    effect_size_type = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'effects_metabolite_phenotype'

class EffectsPhenotypePhenotype(models.Model):
    id = models.IntegerField(primary_key=True, db_index=True)
    phenotype_1 = models.ForeignKey('CohortPhenotype', models.DO_NOTHING, db_column='phenotype_id_1', blank=True, null=True,
                                       related_name='cohort_phenotype_1')
    phenotype_2 = models.ForeignKey('CohortPhenotype', models.DO_NOTHING, db_column='phenotype_id_2', blank=True, null=True,
                                       related_name='cohort_phenotype_2')
    p_value = models.FloatField(blank=True, null=True)
    adjusted_p_value = models.FloatField(blank=True, null=True)
    effect_size = models.FloatField(blank=True, null=True)
    effect_size_type = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'effects_phenotype_phenotype'

class EffectsProteinMetabolite(models.Model):
    id = models.IntegerField(primary_key=True, db_index=True)
    protein = models.ForeignKey('CohortProtein', models.DO_NOTHING, blank=True, null=True, db_index=True)
    metabolite = models.ForeignKey('CohortMetabolite', models.DO_NOTHING, blank=True, null=True)
    p_value = models.FloatField(blank=True, null=True)
    adjusted_p_value = models.FloatField(blank=True, null=True)
    effect_size = models.FloatField(blank=True, null=True)
    effect_size_type = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'effects_protein_metabolite'

class EffectsProteinPhenotype(models.Model):
    id = models.IntegerField(primary_key=True, db_index=True)
    protein = models.ForeignKey('CohortProtein', models.DO_NOTHING, blank=True, null=True, db_index=True)
    phenotype = models.ForeignKey('CohortPhenotype', models.DO_NOTHING, blank=True, null=True)
    p_value = models.FloatField(blank=True, null=True)
    adjusted_p_value = models.FloatField(blank=True, null=True)
    effect_size = models.FloatField(blank=True, null=True)
    effect_size_type = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'effects_protein_phenotype'

class EffectsProteinProtein(models.Model):
    id = models.IntegerField(primary_key=True, db_index=True)
    protein_1 = models.ForeignKey('CohortProtein', models.DO_NOTHING, db_column='protein_id_1', blank=True, null=True,
                                     related_name='cohort_protein_1', db_index=True)
    protein_2 = models.ForeignKey('CohortProtein', models.DO_NOTHING, db_column='protein_id_2', blank=True, null=True,
                                     related_name='cohort_protein_2', db_index=True)
    p_value = models.FloatField(blank=True, null=True)
    adjusted_p_value = models.FloatField(blank=True, null=True)
    effect_size = models.FloatField(blank=True, null=True)
    effect_size_type = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'effects_protein_protein'


#TODO: adjust this model
class VariantAffectsGene(models.Model):
    genomic_variant = models.ForeignKey('GenomicVariant', models.DO_NOTHING, db_column='genomic_variant', blank=True, null=True)
    entrez_id = models.ForeignKey('Gene', models.DO_NOTHING, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'variant_affects_gene'


# 'References' edges map CHRIS nodes to external nodes
class CohortReferencesMetabolite(models.Model):
    id = models.IntegerField(primary_key=True)
    cohort_id = models.ForeignKey('CohortMetabolite', models.DO_NOTHING, blank=True, null=True)
    hmdb_id = models.ForeignKey('Metabolite', models.DO_NOTHING, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'cohort_references_metabolite'

class CohortReferencesDisease(models.Model):
    id = models.IntegerField(primary_key=True)
    cohort_id = models.ForeignKey('CohortPhenotype', models.DO_NOTHING, blank=True, null=True)
    mondo_id = models.ForeignKey('Disorder', models.DO_NOTHING, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'cohort_references_disease'

class CohortReferencesPhenotype(models.Model):
    id = models.IntegerField(primary_key=True)
    cohort_id = models.ForeignKey('CohortPhenotype', models.DO_NOTHING, blank=True, null=True)
    hpo_id = models.ForeignKey('Phenotype', models.DO_NOTHING, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'cohort_references_phenotype'

class CohortReferencesProtein(models.Model):
    id = models.IntegerField(primary_key=True)
    cohort_id = models.ForeignKey('CohortProtein', models.DO_NOTHING, blank=True, null=True)
    uniprot_id = models.ForeignKey('Protein', models.DO_NOTHING, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'cohort_references_protein'


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
    source_id = models.CharField(primary_key=True, blank=True, max_length=200, db_column='source_id')
    target_id = models.CharField(blank=True, null=True, max_length=200, db_column='target_id')

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