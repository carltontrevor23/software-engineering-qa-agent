# Subscription Service Requirements

## Section 2.6: Notification Delivery

Feature: Tier Change Notification Delivery

Acceptance Criteria:
1. Whenever a user's tier changes (upgrade per Section 2.1, downgrade per Section 2.3, or cancellation per Section 2.2), the system must send a notification via the internal notification service (POST /notifications/send).
2. The notification payload must include: user_id, previous_tier, new_tier, and a UTC ISO-8601 timestamp of the change.
3. If the notification service call fails (non-200 response), the tier change itself must still be considered successful and must not be rolled back. The failed notification must instead be logged with a NotificationDeliveryError for later manual review.
4. Notifications must not be sent for refund transactions (Section 2.4), since a refund reverts a tier change that was already notified.
5. Notifications must not be sent for trial period starts (Section 2.5).
