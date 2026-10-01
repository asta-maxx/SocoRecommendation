"""The exemption and test-account lists in the settings. ENG-29 item 3, X-21.

    is_test_account(user_id)   left out of learning, measurement and fraud;
                               the only accounts internal mode serves (ENG-06)
    is_exempt(account_id)      flagged by fraud rules, never actioned (ENG-21)

Each entry carries the account id, the reason, an expiry and who changed it
(reco.config.tunables.AccountEntry). An entry counts until the end of its expiry
day. Every change to the lists is a settings change, so it is logged in
ml_config_changes with the old and new value and who made it (ENG-02 item 4).
"""

from __future__ import annotations

from datetime import date

from reco.config import live
from reco.config.tunables import AccountEntry


def active(entries: list[AccountEntry], today: date | None = None) -> set[str]:
    today = today or date.today()
    return {entry.account_id for entry in entries if entry.expiry >= today}


def test_account_ids(today: date | None = None) -> set[str]:
    return active(live.current().lists.test_accounts, today)


def is_test_account(account_id: str | None, today: date | None = None) -> bool:
    return bool(account_id) and str(account_id).strip().lower() in test_account_ids(today)


def is_exempt(account_id: str | None, today: date | None = None) -> bool:
    return bool(account_id) and str(account_id).strip().lower() in active(live.current().lists.exemptions, today)
