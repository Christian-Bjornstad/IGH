import pytest
import requests

from igh_merge.external import ArrestClient, ExternalAnalysisError
from test_external import candidate_batch, FakeResponse, arrest_text


def test_timeout_retry_preserves_payload(monkeypatch):
    sent = []
    def post(url, **kwargs):
        sent.append((url, kwargs['files']))
        if len(sent) == 1:
            raise requests.Timeout('timeout')
        return FakeResponse(b'<a href="/results/public.tsv">results</a>', url=url)
    monkeypatch.setattr('igh_merge.external.requests.post', post)
    monkeypatch.setattr('igh_merge.external.requests.get', lambda url, **kw: FakeResponse(arrest_text().encode(), url=url))
    result = ArrestClient().submit(candidate_batch())
    assert len(sent) == 2
    assert sent[0][1] == sent[1][1]
    assert result.attempts == 2
    assert result.endpoint == sent[-1][0]


@pytest.mark.parametrize('failure', [requests.exceptions.SSLError('TLS'), requests.HTTPError('400')])
def test_nonretry_errors(monkeypatch, failure):
    attempts = []
    def post(*args, **kw):
        attempts.append(kw)
        raise failure
    monkeypatch.setattr('igh_merge.external.requests.post', post)
    with pytest.raises(ExternalAnalysisError):
        ArrestClient().submit(candidate_batch())
    assert len(attempts) == 1


def test_http_result_link_rejected(monkeypatch):
    monkeypatch.setattr('igh_merge.external.requests.post', lambda *a, **kw: FakeResponse(
        b'<a href="http://bat.infspire.org/result.tsv">results</a>', url=a[0]))
    monkeypatch.setattr('igh_merge.external.requests.get', lambda *a, **kw: pytest.fail('insecure result fetched'))
    with pytest.raises(ExternalAnalysisError):
        ArrestClient().submit(candidate_batch())
