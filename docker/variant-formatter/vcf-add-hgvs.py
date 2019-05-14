#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import absolute_import, division, print_function, unicode_literals

__doc__ = """add HGVS tags to a VCF file on stdin, output to stdout
eg$ vcf-add-hgvs <in.vcf >out.vcf
"""

import argparse
import gzip
import itertools
import logging
import os
import sys

from bioutils.assemblies import get_assemblies

import hgvs.edit
import hgvs.location
import hgvs.posedit
import hgvs.sequencevariant
import hgvs.parser
import hgvs.dataproviders.uta
import hgvs.variantmapper
import hgvs.normalizer

_logger = logging.getLogger(__name__)


def parse_args(argv):
    # parse command line for configuration files
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter, )
    ap.add_argument('--assembly', '-A', default='GRCh37')
    ap.add_argument('--in-filename', '-i', default='-')
    ap.add_argument('--out-filename', '-o', default='-')
    ap.add_argument('--with-c-dot',
                    '-c',
                    default=False,
                    help="add transcript variant projections to c",
                    action='store_true')
    args = ap.parse_args(argv)
    return args


def alts_as_genomic_hgvs(contig_ac_map, r, hdp, keep_left_anchor=False):
    """returns a list of HGVS variants corresponding to the ALTs of the
    given VCF record"""

    def hgvs_from_vcf_record(r, alt_index, normalizer):
        """Creates a genomic SequenceVariant from a VCF record and the specified alt"""
        ref = r.REF
        alt = r.ALT[alt_index].sequence if r.ALT[alt_index] else ''
        start = r.start
        end = r.end

        ac = contig_ac_map[r.CHROM]

        if ref == '' and alt != '':
            # insertion
            end += 1
        else:
            start += 1

        if not keep_left_anchor:
            pfx = os.path.commonprefix([ref, alt])
            lp = len(pfx)
            if lp > 0:
                ref = ref[lp:]
                alt = alt[lp:]
                start += lp

        var_g = hgvs.sequencevariant.SequenceVariant(ac=ac,
                                             type='g',
                                             posedit=hgvs.posedit.PosEdit(
                                                 hgvs.location.Interval(start=hgvs.location.SimplePosition(start),
                                                                        end=hgvs.location.SimplePosition(end),
                                                                        uncertain=False),
                                                 hgvs.edit.NARefAlt(ref=ref if ref != '' else None,
                                                                    alt=alt if alt != '' else None,
                                                                    uncertain=False)))

        var_g = normalizer.normalize(var_g)

        return str(var_g)

    normalizer = hgvs.normalizer.Normalizer(hdp, shuffle_direction=3, cross_boundaries=True)
    hgvs_vars = [hgvs_from_vcf_record(r, alt_index, normalizer) for alt_index in range(len(r.ALT))]
    return hgvs_vars


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    try:
        import vcf
        from vcf.parser import _Info as VcfInfo, field_counts as vcf_field_counts
    except ModuleNotFoundError as e:
        _logger.critical("Because this code is experimental, pyvcf is not an explicit dependency. Try `pip install pyvcf`.")


    opts = parse_args(sys.argv[1:])

    hdp = hgvs.dataproviders.uta.connect(db_url="postgresql://anonymous@localhost:4356/uta/uta_20171026")

    assemblies = get_assemblies()
    assert opts.assembly in assemblies, "{} not in known assemblies (known: {}".format(
        opts.assembly, ','.join(sorted(assemblies.keys())))
    contig_ac_map = {
        s['name']: s['refseq_ac']
        for s in assemblies[opts.assembly]['sequences'] if s['refseq_ac'] is not None
    }

    vr = vcf.Reader(sys.stdin) if opts.in_filename == '-' else vcf.Reader(filename=opts.in_filename)

    vr.infos['HGVS'] = VcfInfo('HGVS', vcf_field_counts['A'], 'String', 'VCF record alleles in HGVS syntax', version=None, source=None)

    vw = vcf.Writer(sys.stdout, vr) if opts.out_filename == '-' else vcf.Writer(filename=opts.out_filename, template=vr)

    for r in vr:
        genomic_hgvs = alts_as_genomic_hgvs(contig_ac_map, r, hdp)
        hgvs_variants = genomic_hgvs
        r.add_info('HGVS', '|'.join(hgvs_variants))
        vw.write_record(r)