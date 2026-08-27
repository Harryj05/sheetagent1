import pytest

from sheetagent.retry import RetryExhausted, with_retry


def test_returns_on_first_success():
    assert with_retry(lambda: 42, sleep=lambda _: None) == 42


def test_retries_then_succeeds():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("boom")
        return "ok"

    assert with_retry(flaky, max_attempts=5, sleep=lambda _: None) == "ok"
    assert calls["n"] == 3


def test_raises_after_exhaustion():
    with pytest.raises(RetryExhausted):
        with_retry(lambda: (_ for _ in ()).throw(IOError("nope")),
                   max_attempts=2, sleep=lambda _: None)


def test_give_up_on_short_circuits():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise FileNotFoundError("missing config")

    with pytest.raises(FileNotFoundError):
        with_retry(fn, max_attempts=5, give_up_on=(FileNotFoundError,),
                   sleep=lambda _: None)
    assert calls["n"] == 1


def test_backoff_grows():
    delays = []
    with pytest.raises(RetryExhausted):
        with_retry(lambda: (_ for _ in ()).throw(ValueError()),
                   max_attempts=4, initial_delay=1, backoff=2,
                   sleep=delays.append)
    assert delays == [1, 2, 4]
