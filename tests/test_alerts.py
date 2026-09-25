from referrals.alerts import Alerter, FailureTracker


def collector(bucket):
    async def send(text):
        bucket.append(text)
    return send


async def test_alerter_rate_limits_per_kind():
    sent, now = [], [0.0]
    alerter = Alerter(collector(sent), min_interval=3600, clock=lambda: now[0])
    assert await alerter.alert("a", "one") is True
    assert await alerter.alert("a", "two") is False
    assert await alerter.alert("b", "three") is True
    now[0] = 3601
    assert await alerter.alert("a", "four") is True
    assert sent == ["⚠️ one", "⚠️ three", "⚠️ four"]


async def test_alerter_swallows_send_errors_and_retries_later():
    calls = []

    async def flaky(text):
        calls.append(text)
        if len(calls) == 1:
            raise RuntimeError("telegram down")

    alerter = Alerter(flaky)
    assert await alerter.alert("a", "x") is False
    assert await alerter.alert("a", "x") is True


def test_failure_tracker():
    tracker = FailureTracker(threshold=3)
    assert [tracker.record("job", ok=False) for _ in range(4)] == [False, False, True, True]
    assert tracker.record("job", ok=True) is False
    assert tracker.record("job", ok=False) is False
