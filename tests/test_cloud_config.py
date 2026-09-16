import pytest
from app.config import Settings


@pytest.mark.parametrize('scheme', ['postgres', 'postgresql', 'postgresql+psycopg'])
def test_render_database_url_uses_installed_driver(scheme):
    cfg = Settings(database_url=scheme + '://user:p%40ss@db:5432/kindred?sslmode=require', _env_file=None)
    assert cfg.database_url == 'postgresql+psycopg://user:p%40ss@db:5432/kindred?sslmode=require'
