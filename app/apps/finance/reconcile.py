"""Reconcile the system against the legacy spreadsheet (PDF §18).

The spreadsheet only stores the results of the year selected in its DRE (B3) and
"FC Mensal" (N2) sheets. For every year we set those cells in a copy and let LibreOffice
recalculate the spreadsheet's own formulas, then compare month by month with what the
system computes after importing the same file (inside a transaction that is rolled back).
"""

import datetime as dt
import re
import shutil
import subprocess
import tempfile
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from django.db import transaction
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill

from apps.companies.models import Company
from apps.finance.importer import ENTRIES_SHEET, import_spreadsheet, parse_workbook
from apps.finance.mapped_import import _parse_amount, _parse_date, norm
from apps.finance.models import NATURAL_TYPE, Group, Transaction, TransactionType
from apps.finance.selectors import MONTH_LABELS, cash_flow_selector, dre_selector
from apps.users.models import Role, User

DRE_SHEET, CASH_SHEET = 'Resultados | DRE', 'FC Mensal'
DRE_YEAR_CELL, CASH_YEAR_CELL, CASH_INITIAL_CELL = 'B3', 'N2', 'L2'
DRE_ROWS = range(6, 69)                       # FATURAMENTO BRUTO .. RESULTADO LÍQUIDO
DRE_MONTH_COL = lambda month: 2 + 2 * (month - 1)  # noqa: E731  (C, E, G... values; D, F... are %)
CASH_ROWS = {5: 'opening', 6: 'inflow', 7: 'outflow', 8: 'closing'}
CASH_LABELS = {'opening': 'Saldo inicial', 'inflow': 'Entradas', 'outflow': 'Saídas', 'closing': 'Saldo final'}
TOLERANCE = Decimal('0.01')
SHEET_MONTHS = ['JANEIRO', 'FEVEREIRO', 'MARÇO', 'ABRIL', 'MAIO', 'JUNHO', 'JULHO', 'AGOSTO',
                'SETEMBRO', 'OUTUBRO', 'NOVEMBRO', 'DEZEMBRO']  # 'Dados Auxiliares' I:J
EXCEL_MAX_ROW = 1_048_576

# Spreadsheet total rows -> system DRE keys (subgroup rows are matched by name inside their section)
DRE_TOTALS = {
    norm('FATURAMENTO BRUTO'): 'gross_sales',
    norm('RECEITAS OPERACIONAIS'): f'group:{Group.OPERATING_REVENUE}',
    norm('CUSTOS VARIÁVEIS'): f'group:{Group.VARIABLE_COSTS}',
    norm('MARGEM DE CONTRIBUIÇÃO'): 'contribution_margin',
    norm('CUSTO FIXOS'): f'group:{Group.FIXED_COSTS}',
    norm('CUSTOS FIXOS'): f'group:{Group.FIXED_COSTS}',
    norm('MARGEM DE LUCRO'): 'profit_margin',
    norm('RECEITAS NÃO OPERACIONAIS'): f'group:{Group.NON_OPERATING_REVENUE}',
    norm('DESPESAS NÃO OPERACIONAIS'): f'group:{Group.NON_OPERATING_EXPENSES}',
    norm('RESULTADO LÍQUIDO'): 'net_result',
}


def _dec(value) -> Decimal:
    return Decimal(str(value)).quantize(TOLERANCE) if isinstance(value, (int, float, Decimal)) else Decimal('0.00')


# Spreadsheet side

def spreadsheet_values(path: Path, years: list[int], soffice: str = 'soffice') -> dict[int, dict]:
    """{year: {'dre': [(row, label, [12 values])], 'cash': {'opening': [12], ...}}}"""
    if not shutil.which(soffice):
        raise RuntimeError(f'LibreOffice not found ("{soffice}"): it recalculates the spreadsheet formulas')
    wb = load_workbook(path)  # with formulas
    # The DRE formulas use ranges past the sheet limit (row 1,052,765): Excel tolerates it,
    # LibreOffice zeroes them. Clamping to the limit keeps the same result.
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith('='):
                    cell.value = re.sub(r'\$(\d{7,})', lambda m: f'${min(int(m.group(1)), EXCEL_MAX_ROW)}', cell.value)

    result = {}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        profile = tmp / 'profile' / 'user'
        profile.mkdir(parents=True)
        # Always recalculate on load (the default keeps the stale cached values)
        (profile / 'registrymodifications.xcu').write_text(
            '<?xml version="1.0" encoding="UTF-8"?><oor:items xmlns:oor="http://openoffice.org/2001/registry" '
            'xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            '<item oor:path="/org.openoffice.Office.Calc/Formula/Load"><prop oor:name="OOXMLRecalcMode" '
            'oor:op="fuse"><value>0</value></prop></item></oor:items>'
        )
        for year in years:
            wb[DRE_SHEET][DRE_YEAR_CELL] = year
            wb[CASH_SHEET][CASH_YEAR_CELL] = year
            source = tmp / f'in-{year}.xlsx'
            wb.save(source)
            out = tmp / 'out'
            subprocess.run(
                [soffice, f'-env:UserInstallation=file://{tmp / "profile"}', '--headless',
                 '--convert-to', 'xlsx', '--outdir', str(out), str(source)],
                check=True, capture_output=True, timeout=600,
            )
            result[year] = _read_recalculated(out / source.name)
    return result


def _read_recalculated(path: Path) -> dict:
    wb = load_workbook(path, read_only=True, data_only=True)
    dre = []
    for number, row in enumerate(wb[DRE_SHEET].iter_rows(
            min_row=DRE_ROWS.start, max_row=DRE_ROWS.stop - 1, max_col=26, values_only=True), start=DRE_ROWS.start):
        if row[1]:
            dre.append((number, str(row[1]).strip(), [_dec(row[DRE_MONTH_COL(m)]) for m in range(1, 13)]))
    cash = {}
    for number, row in enumerate(wb[CASH_SHEET].iter_rows(min_row=5, max_row=8, max_col=14, values_only=True), start=5):
        cash[CASH_ROWS[number]] = [_dec(v) for v in row[2:14]]
    wb.close()
    return {'dre': dre, 'cash': cash}


def cash_initial_balance(path: Path) -> Decimal:
    wb = load_workbook(path, read_only=True, data_only=True)
    value = wb[CASH_SHEET][CASH_INITIAL_CELL].value
    wb.close()
    return _dec(value)


# System side

class _Rollback(Exception):
    pass


def system_values(path: Path, years: list[int]) -> tuple[dict[int, dict], dict]:
    """Import into throwaway companies, compute the reports, roll everything back.

    Returns ({year: {'dre': {key: [12]}, 'cash': {...}, 'reversals': {...}}}, import info).
    """
    initial = cash_initial_balance(path)
    with open(path, 'rb') as f:
        names = sorted({e.company for e in parse_workbook(f).entries if e.company})
    values, info = {}, {}
    try:
        with transaction.atomic():
            user = User.objects.create_user(email='reconcile@invalid.local', password=None, role=Role.FINANCE)
            # Fake CNPJs: unique and never real; everything is rolled back anyway
            default = Company.objects.create(name='(conferência) padrão', cnpj='00000000000000', initial_balance=initial)
            companies = {name: Company.objects.create(name=f'(conferência) {name}', cnpj=f'{i:014d}')
                         for i, name in enumerate(names, start=1)}
            user.companies.add(default, *companies.values())
            with open(path, 'rb') as f:
                imported = import_spreadsheet(f, default_company=default, companies=companies, require_empty=False)
            info = {'skipped': imported.skipped, 'transactions': imported.transactions_created,
                    'sales': imported.sales_created}
            for year in years:
                dre = dre_selector(user=user, year=year)
                flow = cash_flow_selector(user=user, start=dt.date(year, 1, 1), end=dt.date(year, 12, 31))
                values[year] = {
                    'dre': {line['key']: [_dec(v) for v in line['months']] for line in dre['lines']},
                    'labels': {line['key']: (line['label'], line['kind']) for line in dre['lines']},
                    'cash': {k: [_dec(p[k]) for p in flow['periods']] for k in CASH_LABELS},
                    'reversals': _reversals(user, year),
                }
            raise _Rollback
    except _Rollback:
        pass
    return values, info


def _reversals(user: User, year: int) -> dict[tuple[str, int], Decimal]:
    """(subgroup key, month) -> reversal total: the spreadsheet adds them, the system subtracts."""
    totals: dict[tuple[str, int], Decimal] = defaultdict(Decimal)
    for tx in Transaction.objects.filter(company__in=user.companies.all(), date__year=year).select_related('subgroup'):
        if tx.type != NATURAL_TYPE.get(tx.subgroup.group, tx.type):
            totals[(f'subgroup:{tx.subgroup_id}', tx.date.month)] += tx.amount
    return totals


def _skipped_by_month(skipped) -> tuple[dict, dict]:
    """Rows the importer left out, summed where they would have counted (when readable)."""
    by_subgroup, by_flow = defaultdict(Decimal), defaultdict(Decimal)
    for s in skipped:
        if len(s.values) < 7:
            continue  # sales rows
        date, amount, type_, subgroup = _parse_date(s.values[0]), _parse_amount(s.values[2])[0], s.values[3], s.values[6]
        if date and amount:
            by_subgroup[(date.year, date.month, norm(subgroup))] += amount
            flow = {'Entradas': 'inflow', 'Saídas': 'outflow'}.get(str(type_ or '').strip())
            if flow:
                by_flow[(date.year, date.month, flow)] += amount
    return by_subgroup, by_flow


def helper_formula_errors(path: Path) -> list[dict]:
    """Rows whose month/year helper formulas (Lançamentos L/N) read another row's date.

    The spreadsheet DRE sums by those helpers, so such a row lands in the wrong month there.
    """
    formulas = load_workbook(path, read_only=True)[ENTRIES_SHEET]
    values = load_workbook(path, read_only=True, data_only=True)[ENTRIES_SHEET]
    errors = []
    for (number, f_row), v_row in zip(
        enumerate(formulas.iter_rows(min_row=3, max_col=14, values_only=True), start=3),
        values.iter_rows(min_row=3, max_col=14, values_only=True),
    ):
        refs = [m for cell in (f_row[11], f_row[13]) if isinstance(cell, str)
                for m in re.findall(r'B(\d+)', cell)]
        date = _parse_date(v_row[1])
        lands = (v_row[12], v_row[13])  # month name / year the spreadsheet DRE uses
        real = (SHEET_MONTHS[date.month - 1], date.year) if date else None
        if date and refs and any(int(r) != number for r in refs) and lands != real:
            errors.append({
                'row': number, 'date': date, 'amount': _parse_amount(v_row[3])[0] or Decimal(0),
                'subgroup': str(v_row[7] or ''), 'formulas': ' '.join(str(c) for c in (f_row[11], f_row[13])),
                'sheet_month': v_row[12], 'sheet_year': v_row[13],
            })
    return errors


# Comparison

def reconcile(path: Path, years: list[int] | None = None, soffice: str = 'soffice', log=print) -> dict:
    path = Path(path)
    if years is None:
        years = _years_in_file(path)
    log(f'Anos: {years}. Importando no sistema (tudo é desfeito no final)…')
    system, info = system_values(path, years)
    log('Recalculando a planilha no LibreOffice, um ano por vez…')
    sheet = spreadsheet_values(path, years, soffice)
    skipped_subgroup, skipped_flow = _skipped_by_month(info['skipped'])
    formula_errors = helper_formula_errors(path)
    # Where the spreadsheet puts those rows (helper month) instead of their real month
    moved: dict[tuple, Decimal] = defaultdict(Decimal)
    for e in formula_errors:
        moved[(e['date'].year, e['date'].month, norm(e['subgroup']))] -= e['amount']
        if e['sheet_month'] in SHEET_MONTHS and isinstance(e['sheet_year'], (int, float)):
            moved[(int(e['sheet_year']), SHEET_MONTHS.index(e['sheet_month']) + 1, norm(e['subgroup']))] += e['amount']

    dre_diffs, cash_diffs, summary = [], [], []
    for year in years:
        sys_y, sheet_y = system[year], sheet[year]
        by_name = {(norm(label), key) for key, (label, kind) in sys_y['labels'].items() if kind == 'subgroup'}
        compared = matched = 0
        section = None
        for row, label, months in sheet_y['dre']:
            key = DRE_TOTALS.get(norm(label))
            if key and key.startswith('group:'):
                section = key
            if not key:  # subgroup row: same name inside the current section
                candidates = [k for name, k in by_name if name == norm(label)]
                key = next((k for k in candidates if _subgroup_group(sys_y, k) == section), None) \
                    or (candidates[0] if len(candidates) == 1 else None)
            if not key:
                if any(months):
                    dre_diffs.append(_diff(year, row, label, 0, sum(months), Decimal(0),
                                           'Subgrupo da planilha não existe no sistema'))
                continue
            for month in range(1, 13):
                compared += 1
                expected, got = months[month - 1], sys_y['dre'].get(key, [Decimal(0)] * 12)[month - 1]
                if abs(expected - got) <= TOLERANCE:
                    matched += 1
                    continue
                dre_diffs.append(_diff(year, row, label, month, expected, got,
                                       _dre_cause(key, year, month, expected - got, label, sys_y,
                                                  skipped_subgroup, moved)))
        for flow, values in sheet_y['cash'].items():
            for month in range(1, 13):
                compared += 1
                expected, got = values[month - 1], sys_y['cash'][flow][month - 1]
                if abs(expected - got) <= TOLERANCE:
                    matched += 1
                    continue
                if flow in ('opening', 'closing'):
                    cause = 'Saldo: acumula as diferenças de entradas/saídas (deste e de meses anteriores)'
                elif abs((expected - got) - skipped_flow.get((year, month, flow), 0)) <= TOLERANCE:
                    cause = 'Linhas não importadas (aba "Linhas não importadas")'
                else:
                    cause = 'Investigar'
                cash_diffs.append({'year': year, 'line': CASH_LABELS[flow], 'month': month,
                                   'sheet': expected, 'system': got, 'diff': expected - got, 'cause': cause})
        summary.append({'year': year, 'compared': compared, 'matched': matched,
                        'max_diff': max([abs(d['diff']) for d in dre_diffs + cash_diffs if d['year'] == year] or [0])})
    return {'years': years, 'summary': summary, 'dre': dre_diffs, 'cash': cash_diffs,
            'skipped': info['skipped'], 'imported': info, 'formula_errors': formula_errors}


def _subgroup_group(sys_y: dict, key: str) -> str | None:
    # The system DRE lists each subgroup right after its group line
    current = None
    for k, (_, kind) in sys_y['labels'].items():
        if kind == 'group':
            current = k
        if k == key:
            return current
    return None


def _diff(year, row, label, month, expected, got, cause) -> dict:
    return {'year': year, 'row': row, 'line': label, 'month': month, 'sheet': expected,
            'system': got, 'diff': expected - got, 'cause': cause}


def _dre_cause(key, year, month, diff, label, sys_y, skipped_subgroup, moved) -> str:
    """Explain a subgroup difference by its known parts (spreadsheet - system)."""
    if not key.startswith('subgroup:'):
        return 'Reflexo das linhas de subgrupo acima'
    parts = {
        'Erro na planilha: a fórmula de mês/ano lê a data de outra linha (aba "Erros na planilha")':
            moved.get((year, month, norm(label)), Decimal(0)),
        'Estorno: a planilha soma, o sistema subtrai (regra decidida)':
            2 * sys_y['reversals'].get((key, month), Decimal(0)),
        'Linhas não importadas (aba "Linhas não importadas")':
            skipped_subgroup.get((year, month, norm(label)), Decimal(0)),
    }
    present = {cause: value for cause, value in parts.items() if value}
    if present and abs(diff - sum(present.values())) <= TOLERANCE:
        return ' + '.join(present) if len(present) > 1 else next(iter(present))
    return 'Investigar'


def _years_in_file(path: Path) -> list[int]:
    wb = load_workbook(path, read_only=True, data_only=True)
    years = set()
    for row in wb[ENTRIES_SHEET].iter_rows(min_row=3, min_col=2, max_col=2, values_only=True):
        if isinstance(row[0], (dt.date, dt.datetime)) and 2000 < row[0].year < 2100:
            years.add(row[0].year)
    wb.close()
    return sorted(years)


# Report

def write_report(result: dict, output: Path) -> None:
    wb = Workbook()
    bold, money = Font(bold=True), '#,##0.00;[Red]-#,##0.00'
    ok_fill, bad_fill = PatternFill('solid', fgColor='DCFCE7'), PatternFill('solid', fgColor='FEE2E2')

    ws = wb.active
    ws.title = 'Resumo'
    ws.append(['Conferência: sistema × planilha'])
    ws['A1'].font = Font(bold=True, size=14)
    imported = result['imported']
    ws.append([f"Importados: {imported['transactions']} lançamentos e {imported['sales']} vendas · "
               f"{len(result['skipped'])} linha(s) não importada(s) · tolerância R$ 0,01"])
    ws.append([])
    ws.append(['Ano', 'Valores comparados', 'Batem', 'Diferentes', 'Maior diferença'])
    for c in ws[4]:
        c.font = bold
    for s in result['summary']:
        ws.append([s['year'], s['compared'], s['matched'], s['compared'] - s['matched'], s['max_diff']])
        ws.cell(ws.max_row, 5).number_format = money
        ws.cell(ws.max_row, 4).fill = ok_fill if s['compared'] == s['matched'] else bad_fill
    ws.column_dimensions['A'].width = 12
    for col in 'BCDE':
        ws.column_dimensions[col].width = 20

    def table(title, headers, rows, widths):
        sheet = wb.create_sheet(title)
        sheet.append(headers)
        for c in sheet[1]:
            c.font = bold
        for row in rows:
            sheet.append(row)
        for i, width in enumerate(widths, start=1):
            sheet.column_dimensions[sheet.cell(1, i).column_letter].width = width
        sheet.freeze_panes = 'A2'
        return sheet

    month_name = lambda m: MONTH_LABELS[m - 1] if m else 'Ano todo'  # noqa: E731
    sheet = table('Diferenças DRE', ['Ano', 'Linha planilha', 'Conta', 'Mês', 'Planilha', 'Sistema', 'Diferença', 'Causa provável'],
                  [[d['year'], d['row'], d['line'], month_name(d['month']), d['sheet'], d['system'], d['diff'], d['cause']]
                   for d in result['dre']], [8, 14, 36, 10, 16, 16, 16, 60])
    for row in sheet.iter_rows(min_row=2, min_col=5, max_col=7):
        for c in row:
            c.number_format = money
    sheet = table('Diferenças Fluxo', ['Ano', 'Linha', 'Mês', 'Planilha', 'Sistema', 'Diferença', 'Causa provável'],
                  [[d['year'], d['line'], month_name(d['month']), d['sheet'], d['system'], d['diff'], d['cause']]
                   for d in result['cash']], [8, 16, 10, 16, 16, 16, 50])
    for row in sheet.iter_rows(min_row=2, min_col=4, max_col=6):
        for c in row:
            c.number_format = money
    table('Erros na planilha', ['Linha', 'Data real', 'Valor', 'Subgrupo', 'Mês/ano usado pela planilha', 'Fórmulas (L, N)'],
          [[e['row'], e['date'], e['amount'], e['subgroup'], f"{e['sheet_month']} {e['sheet_year']}", e['formulas']]
           for e in result['formula_errors']], [8, 12, 14, 30, 28, 70])
    table('Linhas não importadas', ['Aba', 'Linha', 'Motivo', 'Conteúdo da linha'],
          [['Vendas' if s.reason.startswith('sales:') else 'Lançamentos', s.row, s.reason.removeprefix('sales: '),
            ' | '.join(str(v) for v in s.values if v not in (None, ''))] for s in result['skipped']],
          [14, 8, 34, 120])
    wb.save(output)
