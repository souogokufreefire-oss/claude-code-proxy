from providers.key_pool import ApiKeyPool


def test_key_pool_deduplicates_and_returns_first_key():
    pool = ApiKeyPool((" key1 ", "key1", "key2"))

    assert pool.active_key == "key1"
    assert pool.has_fallbacks()


def test_key_pool_rotates_after_failure():
    pool = ApiKeyPool(("key1", "key2"))

    assert pool.rotate_after_failure("key1") == "key2"
    assert pool.active_key == "key2"


def test_key_pool_returns_none_when_all_keys_fail():
    pool = ApiKeyPool(("key1", "key2"))

    assert pool.rotate_after_failure("key1") == "key2"
    assert pool.rotate_after_failure("key2") is None
    assert pool.active_key is None


def test_key_pool_rotates_after_usage_limit():
    pool = ApiKeyPool(("key1", "key2"), usage_limit=2)

    pool.mark_used("key1")
    assert pool.rotate_if_exhausted("key1") == "key1"
    pool.mark_used("key1")
    assert pool.rotate_if_exhausted("key1") == "key2"
    assert pool.active_key == "key2"
