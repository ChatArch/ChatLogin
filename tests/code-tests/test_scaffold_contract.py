from chatlogin import config
from chatenv import BaseEnvConfig


def test_provider_preserves_brand_namespace():
    assert hasattr(config, "ChatLoginConfig")
    cls = config.ChatLoginConfig
    assert issubclass(cls, BaseEnvConfig)
    assert cls._storage_dir == "ChatLogin"
    assert cls._aliases == ["chatlogin"]


def test_scaffold_does_not_invent_a_login_api_key():
    providers = [value for value in vars(config).values()
                 if isinstance(value, type) and issubclass(value, BaseEnvConfig)
                 and value is not BaseEnvConfig]
    assert len(providers) == 1
    assert not hasattr(providers[0], "CHATLOGIN_API_KEY")
