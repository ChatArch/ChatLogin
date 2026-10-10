"""Managed-account page rendering contracts independent of the core service."""
from pathlib import Path

from chatlogin.ui import LoginUI
from chatlogin.user_ui import UserAdminUI, UserProfileUI


CONTEXT = {
    "assets_path": "/tools/auth/assets",
    "login_url": "/tools/auth/",
    "session_url": "/tools/auth/session",
    "logout_url": "/tools/auth/logout",
    "users_url": "/tools/auth/users",
    "profile_url": "/tools/auth/profile",
    "users_api_url": "/tools/auth/api/users",
    "profile_api_url": "/tools/auth/api/profile",
    "owner_transfer_api_url": "/tools/auth/api/owner/transfer",
}


def test_user_pages_share_login_appearance_and_keep_private_state_out_of_html():
    login_ui = LoginUI(palette="forest", layout="split", appearance="dark")
    users = UserAdminUI(login_ui=login_ui, title='<script>alert("unsafe")</script>').render(CONTEXT)
    profile = UserProfileUI(login_ui=login_ui, title='<script>alert("unsafe")</script>').render(CONTEXT)

    for html, page in ((users, "users"), (profile, "profile")):
        assert '<script>alert("unsafe")</script>' not in html
        assert "&lt;script&gt;" in html
        assert 'data-palette="forest"' in html
        assert 'data-layout="split"' in html
        assert 'data-appearance="dark"' in html
        assert 'src="/tools/auth/assets/users.js"' in html
        assert 'href="/tools/auth/assets/users.css"' in html
        assert 'data-page="' + page + '"' in html
        assert "csrf_token" not in html.lower()
        assert "session_token" not in html.lower()


def test_user_pages_expose_stable_accessible_controls_without_user_html_interpolation():
    users = UserAdminUI().render(CONTEXT)
    for control in (
        "cl-current-user", "cl-users-status", "cl-user-list", "cl-new-user-form",
        "cl-new-username", "cl-new-display-name", "cl-new-password", "cl-new-role",
        "cl-create-user", "cl-owner-transfer-panel", "cl-owner-target",
        "cl-owner-confirm", "cl-owner-password", "cl-transfer-owner", "cl-logout",
    ):
        assert f'id="{control}"' in users

    profile = UserProfileUI().render(CONTEXT)
    for control in (
        "cl-profile-current-user", "cl-profile-status", "cl-profile-form",
        "cl-profile-display-name", "cl-profile-save", "cl-password-form",
        "cl-current-password", "cl-new-password", "cl-change-password",
        "cl-profile-users-link", "cl-logout",
    ):
        assert f'id="{control}"' in profile


def test_user_ui_honors_trusted_template_overrides_and_whole_renderers(tmp_path):
    (tmp_path / "users.html").write_text("<main>Host {{ title }}</main>")
    login_ui = LoginUI(template_dirs=[tmp_path])
    assert UserAdminUI(login_ui=login_ui, title="<unsafe>", template_name="users.html").render(CONTEXT) == "<main>Host &lt;unsafe&gt;</main>"
    assert UserProfileUI(renderer=lambda context: "<main>trusted host renderer</main>").render(CONTEXT) == "<main>trusted host renderer</main>"


def test_managed_client_binds_private_work_to_abortable_auth_generation_without_storage():
    from importlib import resources
    script = (resources.files("chatlogin.web") / "assets/users.js").read_text()
    assert "AbortController" in script
    assert "generation" in script
    assert "credentials: \"same-origin\"" in script
    assert "innerHTML" not in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script
