import pandas as pd

from onecodex.exceptions import OneCodexException
from onecodex.taxonomy import TaxonomyMixin
from onecodex.lib.enums import AlphaDiversityMetric, BetaDiversityMetric, Rank


class DistanceMixin(TaxonomyMixin):
    def alpha_diversity(self, metric=AlphaDiversityMetric.Shannon, rank=Rank.Auto):
        """Calculate the diversity within a community.

        Parameters
        ----------
        metric : {'simpson', 'chao1', 'shannon'}
            The diversity metric to calculate.
        rank : {'auto', 'kingdom', 'phylum', 'class', 'order', 'family', 'genus', 'species'}, optional
            Analysis will be restricted to abundances of taxa at the specified level.

        Returns
        -------
        pandas.DataFrame, a distance matrix.
        """
        import skbio.diversity

        if not AlphaDiversityMetric.has_value(metric):
            raise OneCodexException(
                "For alpha diversity, metric must be one of: {}".format(
                    ", ".join(AlphaDiversityMetric.values())
                )
            )

        df = self.to_df(rank=rank, normalize=self._guess_normalized())

        output = skbio.diversity.alpha_diversity(metric, df.values, df.index, validate=False)

        return pd.DataFrame(output, columns=[metric])

    def beta_diversity(self, metric=BetaDiversityMetric.BrayCurtis, rank=Rank.Auto):
        """Calculate the diversity between two communities.

        Parameters
        ----------
        metric : {'jaccard', 'braycurtis', 'cityblock'}
            The distance metric to calculate.
        rank : {'auto', 'kingdom', 'phylum', 'class', 'order', 'family', 'genus', 'species'}, optional
            Analysis will be restricted to abundances of taxa at the specified level.

        Returns
        -------
        skbio.stats.distance.DistanceMatrix, a distance matrix.
        """
        import skbio.diversity

        if not BetaDiversityMetric.has_value(metric):
            raise OneCodexException(
                "For beta diversity, metric must be one of: {}".format(
                    ", ".join(BetaDiversityMetric.values())
                )
            )

        df = self.to_df(rank=rank, normalize=self._guess_normalized())

        if metric == BetaDiversityMetric.WeightedUnifrac:
            return self.unifrac(weighted=True, rank=rank)
        elif metric == BetaDiversityMetric.UnweightedUnifrac:
            return self.unifrac(weighted=False, rank=rank)

        # NOTE: see #291 for a discussion on using these metrics with normalized read counts. we are
        # explicitly disabling skbio's check for a counts matrix to allow normalized data to make
        # its way into this function.
        return skbio.diversity.beta_diversity(metric, df.values, df.index, validate=False)

    def unifrac(self, weighted=True, rank=Rank.Auto):
        """Calculate the UniFrac beta diversity metric.

        UniFrac takes into account the relatedness of community members. Weighted UniFrac considers
        abundances, unweighted UniFrac considers presence.

        Parameters
        ----------
        weighted : `bool`
            Calculate the weighted (True) or unweighted (False) distance metric.
        rank : {'auto', 'kingdom', 'phylum', 'class', 'order', 'family', 'genus', 'species'}, optional
            Analysis will be restricted to abundances of taxa at the specified level.

        Returns
        -------
        skbio.stats.distance.DistanceMatrix, a distance matrix.
        """
        import skbio.diversity

        df = self.to_df(rank=rank, normalize=self._guess_normalized())

        tax_ids = df.keys().tolist()

        tree = self.tree_build()
        tree = self.tree_prune_rank(tree, rank=df.ocx_rank)

        # there's a bug (?) in skbio where it expects the root to only have
        # one child, so we do a little faking here
        from skbio.tree import TreeNode

        new_tree = TreeNode(name="fake root")
        new_tree.rank = "no rank"
        new_tree.append(tree)

        # then finally run the calculation and return
        if weighted:
            return skbio.diversity.beta_diversity(
                BetaDiversityMetric.WeightedUnifrac,
                df,
                df.index,
                tree=new_tree,
                otu_ids=tax_ids,
                validate=False,
            )
        else:
            return skbio.diversity.beta_diversity(
                BetaDiversityMetric.UnweightedUnifrac,
                df,
                df.index,
                tree=new_tree,
                otu_ids=tax_ids,
                validate=False,
            )
