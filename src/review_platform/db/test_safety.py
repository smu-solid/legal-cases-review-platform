"""Guard destructive tests with an explicit disposable database identity."""

from sqlalchemy.engine import URL, make_url


def validate_test_database(url: str, *, expected_url: str | None) -> None:
    if not expected_url:
        raise ValueError(
            "REVIEW_TEST_DATABASE_URL must explicitly select the disposable test database"
        )
    actual = make_url(url)
    expected = make_url(expected_url)

    def identity(value: URL) -> tuple[str, str | None, int, str | None]:
        return value.get_backend_name(), value.host, value.port or 5432, value.database

    if identity(actual) != identity(expected):
        raise ValueError("test and runtime database identities differ")
    if actual.get_backend_name() != "postgresql" or actual.database != "review_oss_test":
        raise ValueError("tests require the dedicated review_oss_test database")
    if actual.host not in {"127.0.0.1", "localhost", "postgres-test"}:
        raise ValueError("tests require the local disposable database service")
    if actual.host in {"127.0.0.1", "localhost"} and actual.port != 57433:
        raise ValueError("local tests must use isolated port 57433")
