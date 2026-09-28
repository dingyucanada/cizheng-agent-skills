"""Credential destination and text-only contract for the supplied Step Plan endpoint."""
import asyncio

import httpx
import pytest

from cizheng.review_client import StepFunClient


@pytest.mark.parametrize('base', [
    'https://api.stepfun.com/v1',
    'https://api.stepfun.ai/v1',
    'https://api.stepfun.com/step_plan/v1/',
])
def test_explicit_official_bases_are_preserved(monkeypatch, base):
    monkeypatch.setenv('CIZHENG_STEPFUN_URL', base)
    monkeypatch.setenv('CIZHENG_STEPFUN_KEY', 'synthetic-not-a-live-key')
    client = StepFunClient()
    assert client.configured
    assert client.identity()['endpoint'] == base.rstrip('/')


@pytest.mark.parametrize('base', [
    'http://api.stepfun.com/step_plan/v1',
    'https://api.stepfun.com.example/step_plan/v1',
    'https://user@api.stepfun.com/step_plan/v1',
    'https://api.stepfun.com/step_plan/v1?forward=1',
    'https://api.stepfun.com/step_plan/v1/chat/completions',
    'https://other.example/v1',
])
def test_unapproved_or_complete_request_addresses_fail_before_network(monkeypatch, base):
    monkeypatch.setenv('CIZHENG_STEPFUN_URL', base)
    with pytest.raises(ValueError, match='官方 API 地址'):
        StepFunClient()


def test_plan_request_uses_one_suffix_no_redirect_and_only_text(monkeypatch):
    monkeypatch.setenv('CIZHENG_STEPFUN_URL', 'https://api.stepfun.com/step_plan/v1')
    monkeypatch.setenv('CIZHENG_STEPFUN_MODEL', 'step-3.7-flash')
    monkeypatch.setenv('CIZHENG_STEPFUN_KEY', 'synthetic-not-a-live-key')
    native = httpx.AsyncClient
    captured = []

    def handle(request):
        captured.append(request)
        return httpx.Response(200, json={
            'choices': [{'message': {'content': '{"issues":[],"suggested_evidence":"补充资料","limitations":["未查看原图"]}'}}],
            'usage': {'total_tokens': 42},
        })

    def isolated_client(**kwargs):
        assert kwargs['follow_redirects'] is False
        assert kwargs['trust_env'] is False
        return native(transport=httpx.MockTransport(handle), **kwargs)

    monkeypatch.setattr(httpx, 'AsyncClient', isolated_client)
    packet = {'question': 'SYNTHETIC protocol-only text', 'claims': [], 'observations': [], 'references': []}
    result, usage = asyncio.run(StepFunClient().review(packet, 10))
    assert len(captured) == 1
    request = captured[0]
    assert str(request.url) == 'https://api.stepfun.com/step_plan/v1/chat/completions'
    assert request.headers['authorization'] == 'Bearer synthetic-not-a-live-key'
    assert b'image_url' not in request.content and b'base64' not in request.content
    assert result['limitations'] == ['未查看原图']
    assert usage == {'total_tokens': 42}
