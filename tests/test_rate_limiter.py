from app.utils.rate_limiter import RateLimiter


def test_blocks_after_per_minute_limit():
    limiter = RateLimiter(per_minute=3, per_day=100)
    assert limiter.check("1.1.1.1") is None
    assert limiter.check("1.1.1.1") is None
    assert limiter.check("1.1.1.1") is None
    assert limiter.check("1.1.1.1") is not None      # 4th request in a minute is blocked


def test_each_ip_has_its_own_limit():
    limiter = RateLimiter(per_minute=1, per_day=100)
    assert limiter.check("1.1.1.1") is None
    assert limiter.check("2.2.2.2") is None          # a different IP is not affected
    assert limiter.check("1.1.1.1") is not None


def test_daily_limit_applies_to_everyone():
    limiter = RateLimiter(per_minute=100, per_day=2)
    assert limiter.check("1.1.1.1") is None
    assert limiter.check("2.2.2.2") is None
    assert limiter.check("3.3.3.3") is not None      # server-wide daily cap reached