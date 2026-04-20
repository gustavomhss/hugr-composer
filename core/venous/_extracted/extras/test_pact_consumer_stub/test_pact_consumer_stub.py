from __future__ import annotations


@pytest.mark.pact_consumer
def test_pact_consumer_stub() -> None:
    """Stub: demonstrate Pact consumer test pattern.

    Replace this stub with real pact-python consumer tests for each
    external service your app depends on.  See:
    https://docs.pact.io/implementation_guides/python

    Example real test::

        from pact import Consumer, Provider, Like, Term
        pact = Consumer("MyService").has_pact_with(Provider("ExternalAPI"), ...)
        (
            pact.given("state")
            .upon_receiving("a request")
            .with_request("GET", "/resource")
            .will_respond_with(200, body=Like({"id": 1}))
        )
        with pact:
            result = client.get_resource()
            assert result.id == 1
    """
    pytest.skip('Replace with real pact-python consumer contract tests.')
