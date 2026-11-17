from decimal import Decimal

from django.test import SimpleTestCase

from apps.finance.reconcile import _dre_cause

D = Decimal


class ReconcileCauseTests(SimpleTestCase):
    """Which known reason explains a DRE difference (spreadsheet - system)."""

    def cause(self, diff, reversal=0, skipped=0, moved=0, key='subgroup:1'):
        sys_y = {'reversals': {(key, 3): D(reversal)} if reversal else {}}
        return _dre_cause(key, 2026, 3, D(diff), 'Mentorias', sys_y,
                          {(2026, 3, 'mentorias'): D(skipped)} if skipped else {},
                          {(2026, 3, 'mentorias'): D(moved)} if moved else {})

    def test_single_causes(self):
        self.assertTrue(self.cause('200', reversal='100').startswith('Estorno'))  # sheet adds, system subtracts
        self.assertTrue(self.cause('50', skipped='50').startswith('Linhas não importadas'))
        self.assertTrue(self.cause('-2158', moved='-2158').startswith('Erro na planilha'))

    def test_combined_and_unexplained(self):
        combined = self.cause('2448.64', reversal='145.32', moved='2158')
        self.assertIn('Erro na planilha', combined)
        self.assertIn('Estorno', combined)
        self.assertEqual(self.cause('10', reversal='100'), 'Investigar')
        self.assertEqual(self.cause('10'), 'Investigar')

    def test_total_lines_follow_the_subgroups(self):
        self.assertEqual(self.cause('10', key='net_result'), 'Reflexo das linhas de subgrupo acima')
