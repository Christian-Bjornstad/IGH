"""Synthetic SeqCure report fixtures; no clinical sequence or local identifiers."""
from dataclasses import replace
import json

import pytest
import requests

from igh_merge.external import ArrestClient, ExternalAnalysisError, parse_arrest_result, save_arrest_result
from test_external import FakeResponse, arrest_text, candidate_batch


REPORT_URL = 'https://bat.infspire.org/arrest/assignsubsets_results/public.sc.html'
RESPONSE_URL = 'https://bat.infspire.org/cgi-bin/arrest/assignsubsets_html.pl'
REPORT_HTML = '''<html><table>
<tr><th>SeqCure ID [index]</th><th>level</th><th>stage</th><th>IMGT/V-QUEST basic info / ARResT/SeqCure message</th></tr>
<tr><td rowspan="3">SEQ-ABC123 [#0]</td><td></td><td></td><td>160nt; example annotation</td></tr>
<tr><td></td><td>round 1</td><td>productive</td></tr>
<tr><td>note</td><td>round 1</td><td>FR3-IMGT shows mutational load imbalance (60.00% ratio)</td></tr>
</table><table><tr><th>SeqCure ID [index]</th><th>advice</th></tr>
<tr><td>SEQ-ABC123 [#0]</td><td>ok[45] A considerable ratio of mutations was identified.<br>Search for insertions or deletions &amp; review alignments.</td></tr>
</table></html>'''


def install_responses(monkeypatch, *, report_href='/arrest/assignsubsets_results/public.sc.html', report_html=REPORT_HTML, report_error=None):
    link = '' if report_href is None else f'<a href="{report_href}">ARResT/SeqCure report</a>'
    response_html = '<a href="/results/public.tsv">plain-text-formatted results table</a>' + link
    monkeypatch.setattr('igh_merge.external.requests.post', lambda *a, **k: FakeResponse(response_html.encode(), url=RESPONSE_URL))
    fetched = []

    def fake_get(url, **kwargs):
        fetched.append(url)
        if url.endswith('.tsv'):
            return FakeResponse(arrest_text().encode(), url=url)
        if report_error:
            raise report_error
        return FakeResponse(report_html.encode(), url=url)

    monkeypatch.setattr('igh_merge.external.requests.get', fake_get)
    return fetched


def test_client_preserves_seqcure_message_and_advice(monkeypatch, tmp_path):
    install_responses(monkeypatch)
    batch = candidate_batch()
    result = ArrestClient().submit(batch)
    record = result.records[0]
    assert record.subset == 'CLL#2'
    assert record.seqcure_details_status == 'available'
    assert any('60.00%' in text and 'note' in text for text in record.seqcure_messages)
    assert record.seqcure_advice == ('ok[45] A considerable ratio of mutations was identified.\nSearch for insertions or deletions & review alignments.',)
    assert record.seqcure_report_url == REPORT_URL
    path = save_arrest_result(tmp_path, batch, result)
    assert (path.parent / 'seqcure_report.html').read_text(encoding='utf-8') == REPORT_HTML
    audit = json.loads(path.read_text(encoding='utf-8'))
    assert audit['seqcure_report_url'] == REPORT_URL
    assert audit['seqcure_retrieved_at']
    assert audit['seqcure_report_sha256']


@pytest.mark.parametrize('report_href,report_error', [
    (None, None),
    ('http://bat.infspire.org/insecure.html', None),
    ('https://evil.invalid/report.html', None),
    ('https://user:password@bat.infspire.org/report.html', None),
    ('https://bat.infspire.org:8443/report.html', None),
    ('/arrest/assignsubsets_results/public.sc.html', requests.Timeout('expired')),
])
def test_missing_or_unsafe_seqcure_details_do_not_discard_subset(monkeypatch, report_href, report_error):
    fetched = install_responses(monkeypatch, report_href=report_href, report_error=report_error)
    result = ArrestClient().submit(candidate_batch())
    assert result.records[0].subset == 'CLL#2'
    assert result.records[0].seqcure_details_status.startswith('unavailable:')
    assert result.records[0].seqcure_messages == ()
    assert result.seqcure_details_error
    assert not any('evil.invalid' in url or 'user:password' in url or ':8443' in url or url.startswith('http:') for url in fetched)


def test_unknown_id_rejects_details_without_cross_binding(monkeypatch):
    install_responses(monkeypatch, report_html=REPORT_HTML.replace('SEQ-ABC123', 'SEQ-DEF456'))
    result = ArrestClient().submit(candidate_batch())
    assert result.records[0].subset == 'CLL#2'
    assert result.records[0].seqcure_messages == ()
    assert result.records[0].seqcure_details_status.startswith('unavailable:')


def test_multi_sequence_details_follow_external_id_not_display_order(monkeypatch):
    from igh_merge.external import parse_seqcure_report
    batch = candidate_batch()
    second = replace(batch.candidates[0], external_id='SEQ-DEF456', row_index=1)
    batch = replace(batch, candidates=(*batch.candidates, second))
    html = REPORT_HTML.replace('SEQ-ABC123 [#0]', 'SEQ-DEF456 [#1]').replace('60.00%', '10.00%')
    html += REPORT_HTML
    details = parse_seqcure_report(html, batch)
    assert any('60.00%' in t for t in details['SEQ-ABC123'][0])
    assert any('10.00%' in t for t in details['SEQ-DEF456'][0])
    assert len(details['SEQ-ABC123'][1]) == 1


def test_unsafe_redirect_is_not_followed(monkeypatch):
    fetched = install_responses(monkeypatch)
    original_get = requests.get

    def redirect_get(url, **kwargs):
        if url == REPORT_URL:
            response = FakeResponse(b'', url=url)
            response.status_code = 302
            response.headers['Location'] = 'https://evil.invalid/report.html'
            fetched.append(url)
            return response
        return original_get(url, **kwargs)

    monkeypatch.setattr('igh_merge.external.requests.get', redirect_get)
    result = ArrestClient().submit(candidate_batch())
    assert result.records[0].subset == 'CLL#2'
    assert result.seqcure_details_error
    assert not any('evil.invalid' in url for url in fetched)


def test_no_report_table_is_unavailable_instead_of_silently_healthy(monkeypatch):
    install_responses(monkeypatch, report_html='<html>Expired result.</html>')
    result = ArrestClient().submit(candidate_batch())
    assert result.records[0].seqcure_details_status.startswith('unavailable:')
    assert result.records[0].seqcure_messages == ()


def test_actual_seqcure_html_spacer_columns_and_blank_label_rows(monkeypatch):
    html = '''<table><tr><td>SeqCure ID [index]</td><td>&nbsp;</td><td>level</td><td>&nbsp;</td><td>stage</td><td>&nbsp;</td><td>IMGT/V-QUEST basic info / ARResT/SeqCure message</td></tr>
    <tr><td>SEQ-ABC123 [#0]</td><td></td><td></td><td></td><td></td><td></td><td>160nt; annotation</td></tr>
    <tr><td></td><td></td><td><note>note</note></td><td></td><td>round 1</td><td></td><td>FR3-IMGT shows mutational load imbalance (60.00% ratio)</td></tr></table>
    <table><tr><td>SeqCure ID [index]</td><td>&nbsp;</td><td>advice</td></tr><tr><td>SEQ-ABC123 [#0]</td><td></td><td>ok[45] Review separately.</td></tr></table>'''
    install_responses(monkeypatch, report_html=html)
    result = ArrestClient().submit(candidate_batch())
    assert result.records[0].seqcure_details_status == 'available'
    assert result.records[0].seqcure_advice == ('ok[45] Review separately.',)


def test_legacy_report_url_uses_verified_filename_mapping():
    from igh_merge.external import seqcure_report_url_from_results_url
    url = 'https://bat.infspire.org/arrest/assignsubsets_results/fasta0001234567.sc.merged.table.as.res.subtable.tsv'
    assert seqcure_report_url_from_results_url(url) == 'https://bat.infspire.org/arrest/assignsubsets_results/fasta0001234567.sc.report.html'
    with pytest.raises(ExternalAnalysisError):
        seqcure_report_url_from_results_url('https://evil.invalid/anything.tsv')
    with pytest.raises(ExternalAnalysisError):
        seqcure_report_url_from_results_url('https://bat.infspire.org/results/unknown.tsv')


def test_linked_full_advice_is_included_only_for_the_relevant_sequence(monkeypatch):
    html = REPORT_HTML.replace('Search for insertions or deletions &amp; review alignments.',
                               'See <a href="#adv45">full advice 45</a> below.')
    html += '<adv id="adv45"><b>45</b> Mutations.</br>Full relevant advice.</adv>'
    html += '<adv id="adv99">99 Unrelated advice must stay out.</adv>'
    install_responses(monkeypatch, report_html=html)
    result = ArrestClient().submit(candidate_batch())
    assert any('Full relevant advice.' in text for text in result.records[0].seqcure_advice)
    assert not any('Unrelated' in text for text in result.records[0].seqcure_advice)


def test_missing_advice_section_is_explicitly_unavailable(monkeypatch):
    install_responses(monkeypatch, report_html=REPORT_HTML.split('</table>')[0] + '</table>')
    result = ArrestClient().submit(candidate_batch())
    assert result.records[0].subset == 'CLL#2'
    assert result.records[0].seqcure_details_status.startswith('unavailable:')


def test_broken_full_advice_reference_is_explicitly_unavailable(monkeypatch):
    html = REPORT_HTML.replace('Search for insertions or deletions &amp; review alignments.',
                               'See <a href="#adv45">full advice 45</a> below.')
    install_responses(monkeypatch, report_html=html)
    result = ArrestClient().submit(candidate_batch())
    assert result.records[0].subset == 'CLL#2'
    assert result.records[0].seqcure_details_status.startswith('unavailable:')
