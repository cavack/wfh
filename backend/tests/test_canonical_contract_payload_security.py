import pytest
from pydantic import ValidationError

from waterfallhunter.core.contracts import NotificationEvent
from test_canonical_contracts import _valid_notification_event


@pytest.mark.parametrize(
    "key",
    [
        "apitoken",
        "accesstoken",
        "authtoken",
        "bearertoken",
        "usersecret",
        "tokens",
        "credentials",
    ],
)
def test_notification_event_rejects_concatenated_or_plural_secret_like_keys(key):
    invalid_event = _valid_notification_event(
        payload={"metadata": {key: "must-not-be-accepted"}},
    )

    with pytest.raises(ValidationError):
        NotificationEvent(**invalid_event)
