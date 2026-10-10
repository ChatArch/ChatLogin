# ChatVoice Legacy Schema Integration

!!! warning "Unreleased preview"
    This page describes a candidate provider/consumer pair. Public ChatLogin 0.1.6 and ChatVoice 0.4.1 do not necessarily include these new APIs. Preview environments should use the reviewed matching wheel pair. Stable installation should adopt the capability after a matching release.

This integration is for hosts that already use ChatVoice/Speakr SQLite `accounts` and `auth_sessions`. It preserves original accounts, password material, session relationships, business `owner_id`, API-token ownership, meetings, conversations, and recordings while exposing the same account directory through ChatLogin managed users.

## Supported Schema Adoption

```python
from chatlogin.backends import (
    ChatVoiceManagedStore,
    adopt_owner,
    initialize_chatvoice_managed_schema,
)
from chatlogin.managed import ManagedUsers

store = ChatVoiceManagedStore(connect, lock, clock, max_users=10000, max_sessions=10000)
store.initialize()
users = ManagedUsers(store, session_namespace="chatvoice", ttl=86400, clock=clock)

owner = adopt_owner(store, "admin@example.invalid")
```

`connect`, `lock`, and `clock` come from the trusted same-process host and point at the same ChatVoice database and mutual-exclusion boundary. `initialize_chatvoice_managed_schema(connection)` may be called during explicit host database setup. Migration is not an import side effect and not a public HTTP bootstrap.

## Data Preservation

| Original data | Handling after integration |
| --- | --- |
| `accounts.id` | Remains the stable `user_id`; no rebuild or reassignment |
| `account` / `display_name` | Source for managed username/display name |
| `password_salt` / `password_hash` | Original bytes are preserved; old passwords are not rehashed |
| Business-table `owner_id` | Continues to reference the original stable account id; managed `OWNER` is not a business-record bypass |
| `auth_sessions` | Continues to resolve through the same cookie/session relationship; role, status, or password-security changes invalidate affected old sessions |
| API tokens | Disabled or deleted accounts are denied without deleting preserved rows |

Schema initialization is explicit, idempotent, and additive. It adds management columns such as role/status/revision to legacy accounts, defaults old accounts to enabled `USER`, and installs the one-enabled-owner constraint. It does not delete old rows, copy accounts into a second user database, or rewrite business ownership.

## Owner Adoption

`adopt_owner(store, exact_existing_account_or_id) -> UserRecord` is only for one-time adoption of an exact existing account or id:

- It fails when an owner already exists.
- The target must already exist in original `accounts`.
- Adoption sets that account to enabled `OWNER`, increments its auth revision, and returns a credential-free `UserRecord`.
- Other existing accounts remain enabled `USER` unless a later owner/admin action changes them.

`admin@example.invalid` is a synthetic placeholder. Production selection is performed by trusted host Python setup, without writing real account names, user IDs, hashes, or tokens into public docs, command history, or logs.

## Permissions and Trust Boundary

| Boundary | Meaning |
| --- | --- |
| Public signup | Not provided. ChatVoice native account provisioning remains invite-only/trusted tooling |
| Host connector | `connect`/`lock` are trusted same-process interfaces; this does not defend against hostile in-process code |
| Management roles | owner/admin/user manage the account directory; business meetings, audio, API tokens, and model calls still need host ACLs |
| Owner meaning | `OWNER` is the account-directory owner, not omniscient access to all business data |
| Session invalidation | Role, status, deletion, password change, and owner transfer invalidate affected sessions through revision checks |
| Owner transfer | Handled by the managed-users owner-only atomic transfer flow |

The host still enforces business authorization on routes, such as meeting `owner_id`, voice-job ownership, read-token scopes, and denial for disabled/deleted accounts.

